# Architecture — ETAT-MAJOR SNIPER EA

Document de référence de la Phase 2 (moteur de replay). Il décrit les
composants, le modèle temporel, les hypothèses de simulation et les limites
connues.

---

## 1. Principes

1. **Déterminisme.** Aucun appel à l'horloge murale, aucun aléa non semé,
   aucune dépendance à l'ordre d'itération d'un dictionnaire non trié. Deux
   exécutions identiques produisent des rapports identiques octet pour octet.
2. **Séparation des responsabilités.** Données, stratégie, risque, exécution
   et reporting sont des modules distincts. Une stratégie ne peut pas écrire
   dans le portefeuille ni contourner l'autorité de risque.
3. **Traçabilité.** Chaque décision (signal, verdict du risque, soumission,
   exécution, frais) est journalisée avec son horodatage simulé.
4. **Cloisonnement.** Le code de la Phase 2 ne possède aucune capacité
   d'envoi d'ordre : il n'importe aucun SDK broker et n'ouvre aucun socket.

## 2. Vue d'ensemble

```text
                CSV / Parquet (Phase 3)
                        │
                        ▼
             ┌──────────────────────┐
             │  data.loader         │  validation, normalisation UTC
             │  data.validation     │  rapport de qualité
             └──────────┬───────────┘
                        │ Dataset (bars immuables)
                        ▼
             ┌──────────────────────┐
             │  replay.engine       │  horloge simulée, ordre chronologique
             └───────┬────────┬─────┘
                     │        │
        visible bars │        │ proposals (Signal)
                     ▼        ▼
             ┌───────────────┐   ┌──────────────────┐
             │ strategies    │   │ risk.governor    │  veto indépendant
             │ (contrat)    │   │ (autorisation)   │
             └───────────────┘   └────────┬─────────┘
                                          │ RiskDecision
                                          ▼
                                   ┌─────────────┐
                                   │ execution   │  ordre → remplissage
                                   │ .broker     │
                                   └──────┬──────┘
                                          │ Fill
                                          ▼
                                   ┌─────────────┐
                                   │ execution   │  comptabilité
                                   │ .accounting │  (Portfolio)
                                   └──────┬──────┘
                                          ▼
                             ┌────────────────────────┐
                             │ reporting.report        │
                             │ core.journal (JSONL)    │
                             └────────────────────────┘
```

## 3. Modèle temporel

Une bougie `i` couvre l'intervalle `[ts_open(i), ts_close(i))` avec
`ts_close(i) - ts_open(i) = timeframe`.

| Instant | Traitement |
| --- | --- |
| `ts_open(i)` | le broker traite les ordres acceptés à la clôture de `i-1` ; les ordres marché sont exécutés au prix d'ouverture de `i` |
| `ts_close(i)` | la bougie devient observable ; le portefeuille est valorisé au cours de clôture ; la stratégie reçoit la bougie et peut émettre des propositions |
| `ts_close(i)` | les propositions passent par l'autorité de risque puis sont soumises au broker, en attente de `ts_open(i+1)` |

**Conséquence (règle anti-look-ahead).** Le prix d'exécution d'un signal
issu de la bougie `i` est l'ouverture de la bougie `i+1` — une information
indisponible au moment de la décision. Sur un dataset discontinu (gap), le
prix d'exécution est le prix d'ouverture après le gap, jamais le prix de
clôture de la bougie de signal.

La stratégie ne reçoit que `visible_bars`, une **vue bornée** sur la tranche
`bars[0..i]` (`strategies.base.VisibleBars`). Le moteur ne lui transmet aucune
donnée future et aucun accès direct au dataset complet n'est exposé.

La vue ne **copie** rien : elle conserve la séquence sous-jacente et une
limite, ce qui rend l'accès O(1). Une implémentation antérieure qui
recopiait l'historique visible à chaque bougie rendait le rejeu quadratique
(114 µs/bougie à 20 000 bougies) ; elle a été remplacée en Phase A
(cf. `docs/audit/PHASE_A_REPORT.md`).

Un index hors de la fenêtre visible lève une `IndexError` explicite : il est
impossible de lire une bougie future, y compris par un index négatif.

**Horloge.** `core.clock.SimClock` porte un timestamp en nanoseconds. Elle
avance au fil du replay et refuse de reculer. Aucun composant ne lit
`time.time()`.

## 4. Modèle d'exécution

Le broker simulé (`execution.broker.SimulatedBroker`) est paramétré :

| Paramètre | Unité | Effet |
| --- | --- | --- |
| `spread_price` | distance de prix absolue | demi-spread appliqué de façon adverse à chaque exécution |
| `slippage_price` | distance de prix absolue | dérive adverse systématique |
| `slippage_random_max` | distance de prix absolue | composante aléatoire uniforme, semée |
| `commission_per_lot_per_side` | devise du compte, par lot et par côté | entrée et sortie sont facturées séparément |
| `commission_fixed_per_order` | devise du compte | commission forfaitaire par ordre exécuté |
| `lot_size` | unités instrument | nombre d'unités composant un lot (100 000 pour un contrat FX standard) |
| `reject_probability` | probabilité | rejet aléatoire du broker (scénario d'incident) |

Règles d'exécution :

* **Marché** : exécuté à l'ouverture de la bougie suivante.
* **Limite** : exécuté si la bougie touche le prix limite ; prix de
  transaction = prix limite (+/- slippage adverse).
* **Stop** : déclenché si la bougie touche le niveau ; si l'ouverture de la
  bougie est déjà au-delà du niveau, exécution au prix d'ouverture (gap).
* **Intra-bougie** : si une bougie touche à la fois un stop et une cible,
  Phase 2 n'exécute qu'un seul ordre par bougie, dans l'ordre de soumission.
  Cette ambiguïté est **conservatrice** et documentée ; le traitement fin
  (tick / OHLC ordonnés) relève de la Phase 4.

## 5. Comptabilité

`execution.accounting.Portfolio` est l'unique détenteur de la monnaie.

Invariants (testés) :

```text
cash      == capital_initial + pnl_realise - frais
equity    == cash + pnl_non_realise
pnl_net   == pnl_realise + pnl_non_realise - frais
```

Les frais sont débités exactement une fois, à la clôture de chaque
remplissage. Le prix moyen de position est pondéré par les quantités. Un
retournement de position réinitialise le prix moyen au prix de
l'exécution.

## 6. Autorité de risque

`risk.governor.RiskGovernor` est un protocole minimal :

```python
def authorize(self, request: OrderRequest, snapshot: PortfolioSnapshot) -> RiskDecision
```

`MinimalRiskGovernor` implémente en Phase 2 : taille de position maximale,
notionnel maximal, nombre de positions ouvertes, arrêt global. L'implémentation
détaillée (perte journalière, drawdown, exposition corrélée, profils de
challenge) est prévue en Phase 5 et remplacera le governor par injection,
sans modifier le moteur de stratégie.

Un ordre refusé : (1) ne modifie ni la position ni les liquidités, (2) est
journalisé avec son motif, (3) n'ouvre aucun chemin alternatif.

Seule exception documentée : la fermeture de fin de replay, qui est une
**réduction** d'exposition et non une nouvelle entrée ; elle n'est pas
soumise au governor mais sa politique est explicite et journalisée.

## 7. Fin de replay

Politique `CLOSE_AT_LAST_PRICE` (défaut) :

1. tous les ordres en attente sont annulés (journal `ORDER_CANCELLED`) ;
2. les positions ouvertes sont fermées au dernier cours connu, en appliquant
   spread, slippage et commission (ordre de marché synthétique) ;
3. le rapport indique la politique appliquée.

Politique `MARK_TO_MARKET` : les positions restent ouvertes et sont valorisées
au dernier cours.

## 8. Journal et rapports

* `core.journal.Journal` : séquence d'événements horodatés, sérialisable en
  JSONL (`artifacts/journal.jsonl`).
* `reporting.report.build_report` : rapport JSON — symbole, période, nombre de
  bougies, ordres, exécutions, transactions, frais, capital initial et final,
  PnL net, motifs de rejet, politique de fin de replay, empreintes de
  configuration et de dataset.
* `reporting.report.render_summary` : résumé console.

Les rapports ne contiennent aucune information d'horloge murale : c'est ce qui
permet la comparaison octet pour octet entre deux exécutions.

## 8 bis. Modes de fonctionnement

Le mode est paramétré et validé au démarrage (`core.types.OperatingMode`) :

| Mode | État | Commentaire |
| --- | --- | --- |
| `LAB` | autorisé | laboratoire, simulation pure |
| `CHALLENGE_SIM` | autorisé | simulation de challenge (Challenge Engine) |
| `PAPER` | **refusé** | aucun adaptateur de données live n'existe dans ce build (Mission 8) |
| `PRODUCTION` | **refusé** | exige une autorisation humaine explicite (Mission 10) |

Le mode actif figure dans chaque rapport. Le passage d'un mode à l'autre
n'est jamais implicite : un mode non disponible arrête le programme avec un
message explicite.

## 9. Limites connues de la Phase 2

| Limite | Traitement | Phase cible |
| --- | --- | --- |
| Ambiguïté intra-bougie (stop vs cible) | une seule exécution par bougie, hypothèse conservatrice | Phase 4 |
| Modèle mono-instrument | le portefeuille et le risque gèrent un symbole par instance | Phase 5 |
| Swaps et financement overnight | non implémentés | Phase 4 |
| Marge et levier | non implémentés (notionnel seul) | Phase 5 |
| Format de données | CSV uniquement | Phase 3 (Parquet) |
| Multi-timeframe et Horton-Strahler | non implémentés | Phase 6 |
| MT5 / broker réel | hors périmètre de la Phase 2 | Phase 9 |

## 10. Ce que la Phase 2 ne prétend pas démontrer

* Que la stratégie de démonstration est rentable : elle ne l'est pas et n'a
  pas vocation à l'être ; elle sert à éprouver le cycle de vie des ordres.
* Que la simulation reproduit fidèlement un broker réel : les coûts, le
  spread, le slippage et la microstructure sont modélisés de façon simple et
  documentée, pas mesurés sur un flux de carnet.
* Que le moteur est prêt pour la production : il ne sait ni dialoguer avec
  MT5, ni réconcilier un compte réel, ni exécuter une politique de challenge
  prop firm.

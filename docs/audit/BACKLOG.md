# Backlog des écarts — audit MISSION 0

**Source :** `docs/audit/INITIAL_AUDIT.md` (preuves exécutables)
**Date :** 2026-10-22
**Statut :** proposé, en attente de validation du chef de projet

Gravité : **Majeure** (bloque une porte de validation ou produit un résultat
faux) · **Mineure** (contrat incomplet, code mort, écart code/documentation) ·
**Absence** (composant manquant par rapport à la feuille de route).

---

## C1 — Correction AUDIT-D1 : reprise non quadratique (MAJEURE)

**Constat.** `src/etatmajor/replay/engine.py:205` recopie l'historique
visible à chaque bougie : `visible_bars=tuple(self.dataset.bars[: index + 1])`.
Mesure : 43,0 µs/bougie à 240 bougies contre 114,2 µs/bougie à 20 000
(quadratique). Projection : ~95 min pour 1 M de bougies.

**Correctif proposé.** Introduire une vue bornée en lecture seule
(`data/models.py` ou `strategies/base.py`) :

```python
class VisibleBars(Sequence):
    """Vue bornée de l'historique, sans copie (O(1) par construction)."""
    def __init__(self, bars: Sequence[Bar], limit: int) -> None: ...
    def __len__(self) -> int: return self._limit
    def __getitem__(self, index): ...   # indices relatifs, négatif depuis la fin
```

et remplacer l'argument du contexte par `VisibleBars(self.dataset.bars, index + 1)`.

**Contraintes de non-régression.**

1. le test `test_strategy_cannot_observe_future_bars` doit rester vert ;
2. un nouveau test doit vérifier qu'une stratégie ne peut pas lire une barre
   future via `visible_bars[-1]` au-delà de la limite (index négatif hors
   bornes → erreur, pas de fuite) ;
3. le débit à 20 000 bougies doit repasser sous **10 µs/bougie** (soit un gain
   d'un facteur 10) ; le seuil est enregistré dans le test de performance ;
4. aucun changement du contenu du rapport (l'empreinte de référence doit être
   inchangée) — preuve que la correction est purement interne.

**Taille :** S. **Dépend de :** rien. **Bloque :** Mission 12, Mission 13.

---

## C2 — Correction AUDIT-D2 / D3 : cycle de vie et expiration (MINEURE)

**Constat.** `on_stop` est déclaré dans le contrat
(`strategies/base.py:71`) et dans la stratégie de démonstration
(`strategies/demo.py:93`) mais **jamais appelé** par le moteur. Le champ
`Signal.expires_ts_ns` (`core/events.py:36`) n'est **jamais appliqué**.

**Correctif proposé.**

1. le moteur appelle `strategy.on_stop(context)` après la politique de fin de
   replay, avec un contexte explicitement marqué `final=True` ;
2. le moteur **refuse** une proposition dont `expires_ts_ns` est dépassé
   (`SignalExpired`), et journalise le motif ;
3. le signal expiré est comptabilisé comme une **abstention**, pas comme un
   rejet du risque (distinction à journaliser).

**Contraintes.** Test : un signal expirant est rejeté sans exécution ; un
`on_stop` est appelé une fois et une seule ; le journal contient l'événement.

**Taille :** S.

---

## C3 — Assainissement du contrat (MINEURES)

| Écart | Correctif |
| --- | --- |
| D5 — `mode` codé en dur (`reporting/report.py:62`) | énumérateur `OperatingMode` (`LAB`, `CHALLENGE_SIM`, `PAPER`) dans `core/types.py`, champ de configuration validé, valeur reprise dans le rapport, mode `PAPER` refusé tant qu'aucun adaptateur de données live n'existe |
| D4 — `quantity_step` jamais appliqué | contrôle d'alignement dans `SimulatedBroker._pre_trade_check` + test de frontière |
| D6 — exceptions jamais levées | le moteur lève `StrategyError` (contrat de stratégie violé) et `ExecutionError` (refus du broker à la clôture finale) au lieu de `except Exception` ; suppression du `except Exception` nu |
| D7 — API morte (9 symboles) | brancher (`Portfolio.notional` utilisé par le governor, `Bar.duration_ns` utilisé par le loader pour le contrôle de cohérence, `StrategyContext.last_bars` utilisé par la stratégie de démonstration) **ou** supprimer (`TimeInForce`, `OrderSide.opposite`, `DataQualityReport.add_error`, `StrategyContext.close_price`, `Portfolio.open_symbols`) ; `RiskRejected` devient le type levé par le chemin de refus |
| D8 — fingerprint recalculé 3 fois | calcul unique mis en cache dans `Dataset` |

**Contraintes.** Le rapport de référence versionné doit rester identique
(correction interne). La couverture ne doit pas diminuer.

**Taille :** M.

---

## C4 — Compléter la Mission 1 : socle de contrats (MAJEURE)

Manquants, exigés par la Mission 1 du CDC et par les Missions 5 à 7 :

| Modèle | Contenu attendu |
| --- | --- |
| `MissionPlan` | instrument, sens, type d'ordre, prix d'entrée, invalidation, stop, objectif, taille, risque, coûts estimés, durée max, conditions d'annulation, expiration |
| `TradeIntent` | résultat d'un plan, prêt à être soumis au RiskGovernor |
| `AccountState` | capital, solde, equity, marge utilisée/disponible, devise, horodatage |
| `PortfolioState` | positions, ordres ouverts, exposition par instrument et globale |
| `MarketSnapshot` | bid/ask, spread courant, volumes, fraîcheur de la donnée |
| `MarketTick` | tick unitaire (préparation de l'adaptateur MT5) |
| `OrderResult` | résultat d'un ordre (accepté / rejeté / rempli) |
| `ExecutionEvent` | événement d'exécution typé (complète `JournalEntry`) |
| `ChallengeState` | `READY`, `RUNNING`, `PASSED`, `FAILED`, `INVALID`, `REVIEW_REQUIRED` |

**Ajouts transverses :**

* identifiants : `session_id`, `config_version`, `strategy_version` déjà
  présent mais non horodaté ;
* politique d'horodatage et de fuseau documentée (UTC ns) ;
* politique de décimaux et de devise par instrument ;
* `challenges/` et `profiles/` : emplacements des profils de challenge ;
* interdiction structurelle : `core`/`data`/`execution`/`risk` ne peuvent pas
  importer `replay` (règle à faire vérifier par un test d'architecture, pas
  seulement par une revue).

**Taille :** M. **Bloque :** Missions 5, 6, 7.

---

## C5 — Mission 3 : catalogue d'instruments et provenance (MAJEURE)

| Livrable | Contenu |
| --- | --- |
| `data/instruments.py` | fiche instrument : digits, lot size, tick value, volume min/max, pas de volume, horaires, swaps, commissions, marge, devise — versionnée par broker |
| `data/provenance.py` | registre des imports : fichier source, SHA-256, date, transformations, dataset versionné |
| `data/calendar.py` | sessions, changements d'heure, jours fériés, distinction cotation normale / perte de données (corrige D9) |
| `data/parquet.py` | stockage normalisé (Parquet) et brut immuable |
| import MT5 | lecture d'export `.csv` / `.txt` MetaQuotes |

**Taille :** M. **Bloque :** Porte G4 (fidélité opérationnelle).

---

## C6 — Mission 7 : Challenge Engine et profil The5ers (MAJEURE)

| Livrable | Contenu |
| --- | --- |
| `challenge/profile.py` | `ChallengeProfile` versionné : capital, objectif, perte journalière, perte totale, méthode de calcul, heure et fuseau de réinitialisation, jours de trading minimaux, durée, restrictions d'instruments et d'événements, conditions de réussite/échec, source officielle et date de vérification |
| `challenge/engine.py` | machine à états `READY → RUNNING → PASSED/FAILED/INVALID/REVIEW_REQUIRED`, contrôle à chaque événement, motif explicite par verdict, marge de sécurité |
| `challenge/profiles/the5ers_high_stakes_2500.yaml` | profil de référence, **uniquement** avec des règles vérifiées et datées |
| tests | frontières exactes de chaque règle (juste avant / au seuil / juste après) |

**Règle absolue :** aucune règle de challenge ne peut être supposée. Si une
règle n'est pas vérifiée dans la documentation officielle et datée, le
profil est marqué `INVALID` et le simulateur refuse de conclure.

**Taille :** L.

---

## C7 — Mission 5 : RiskGovernor conscient du challenge (MAJEURE)

Extension de `risk/governor.py` : perte journalière (solde ou equity selon la
règle du profil), perte totale, drawdown statique et trailing, exposition et
corrélation, refus des ordres sans stop, kill switch persistant, état sûr
après redémarrage, journalisation de chaque autorisation et refus, tests
d'impossibilité de contournement.

**Taille :** L. **Porte :** G2.

---

## C8 — Mission 6 : Sniper Engine et régime (MAJEURE)

Détecteur de régime (tendance, range, expansion/contraction, conditions
d'exécution dégradées), familles de setups (breakout/retest, pullback,
abstention), déclencheur, Mission Planner, règles d'invalidation, journal des
raisons de décision, versionnement des stratégies.

**Taille :** L.

---

## C9 — Mission 12 : Performance Lab (MAJEURE)

Métriques (PnL net, drawdown, espérance, profit factor, durée d'exposition,
résultats par régime/session/instrument), séparation entraînement / validation
/ test final, walk-forward, Monte-Carlo, sensibilité aux paramètres, registre
des expériences, protection de la version validée.

**Taille :** L. **Dépend de :** C1 (volume), C6/C7 (conformité), C8 (stratégie).

---

## Ordre de correction recommandé

```text
C1 ──▶ C2 ──▶ C3 ──▶ C4 ──▶ C5 ──▶ C6 ──▶ C7 ──▶ C8 ──▶ C9
 │      │      │      │      │      │      │      │      │
 └──────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┘
                    audit + validation du chef de projet
```

Les corrections **C1 à C3** ne créent aucune capacité nouvelle : elles
rendent le socle conforme à ce qu'il annonce. Elles sont prerequisite à toute
affirmation de fiabilité des résultats, et C1 conditionne la faisabilité des
campagnes de la Mission 12.

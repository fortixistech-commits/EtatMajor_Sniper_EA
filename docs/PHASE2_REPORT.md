# Rapport de livraison — Phase 2 : moteur de replay déterministe

| | |
| --- | --- |
| Projet | ETAT-MAJOR SNIPER EA |
| Phase | 2 — moteur de replay historique |
| Branche | `feat/phase-2-replay-engine` |
| Dépôt | `fortixistech-commits/EtatMajor_Sniper_EA` |
| Date | 2026-10-22 |
| Mode | LABORATOIRE (simulation uniquement) |

> Aucun ordre réel n'a été envoyé, aucune connexion broker n'a été ouverte,
> aucun identifiant de compte n'est requis. Le moteur n'importe aucun SDK
> broker et n'ouvre aucun socket (vérifié par test).

---

## 1. État initial du dépôt

| Élément | Constat |
| --- | --- |
| Branche par défaut | `main`, **sans aucun commit** (dépôt vide) |
| Contenu initial | aucun fichier (le dépôt ne contenait que `.git`) |
| Historique | inexistant — aucun fichier existant n'a été supprimé ni écrasé |
| Dépendances / tests | aucun |

Le dépôt ayant été créé vide, la branche `main` a d'abord été amorcée avec le
seul commit de fondation (packaging, configuration, fichiers d'environnement),
sur lequel la branche de travail `feat/phase-2-replay-engine` a été créée.
La Pull Request ne porte donc que sur la Phase 2.

Un fichier `tests/TestEtatMajorSniper.mq5` avait été créé lors d'un échange
antérieur (amorçage du dépôt). Il a été **retiré** au début de la Phase 2 :
l'architecture retenue est Python (le cahier des charges réserve MQL5 aux
composants devant impérativement rester dans MT5, ce qui n'est le cas d'aucun
composant de la Phase 2). La suppression est justifiée ici et tracée dans le
premier commit.

## 2. Environnement

| Élément | Valeur |
| --- | --- |
| Système | Linux 6.17.0-PRoot-Distro, aarch64 |
| Python | CPython 3.13.7 (prise en charge : >= 3.11) |
| pip | 25.1.1 |
| Git | 2.51.0 |
| pytest | 7.3.1 (système), >= 7.4 (projet) |
| NautilusTrader | **1.231.0**, installé et exécuté dans un venv isolé |
| GitHub CLI | absent de la machine (voir §9) |

## 3. Traçabilité des travaux

`main` : 1 commit de fondation (`chore: bootstrap project packaging,
configuration and environment files`).

Branche `feat/phase-2-replay-engine` (8 commits au-dessus de `main`) :

| # | Portée |
| --- | --- |
| 1 | Fondation : `.gitignore`, `pyproject.toml`, configuration, documentation Phase 0/1 |
| 2 | Modèles, horloge, erreurs, journal, configuration validée |
| 3 | Chargement et validation des données OHLC |
| 4 | Broker simulé et comptabilité du portefeuille |
| 5 | Autorité de risque, contrat de stratégie, stratégie de démonstration |
| 6 | Moteur de replay, politique de fin de replay, rapport et CLI |
| 7 | Suite de tests (unitaires, intégration, acceptation) |
| 8 | Dataset d'exemple, sonde NautilusTrader, CI et rapport de phase |

## 4. Fichiers livrés

```text
pyproject.toml                        packaging, entry point, configuration pytest
.gitignore                            secrets, artefacts, environnements
README.md                             présentation, installation, exécution
configs/simulation.toml               configuration de référence du laboratoire
configs/risk.toml                     configuration de référence du risque
data/sample_eurusd_1m.csv             dataset synthétique (240 bougies, seed 20260105)
scripts/generate_sample_data.py       régénération déterministe du dataset
scripts/run_replay.sh                 commande reproductible de replay
scripts/run_nautilus_probe.sh         sonde d'évaluation NautilusTrader (venv isolé)
scripts/probe_nautilus.py             prototype NautilusTrader (hors moteur de production)
src/etatmajor/cli.py                  interface en ligne de commande
src/etatmajor/core/{clock,config,errors,events,journal,types}.py
src/etatmajor/data/{loader,models,validation}.py
src/etatmajor/execution/{accounting,broker}.py
src/etatmajor/replay/engine.py        moteur de replay
src/etatmajor/risk/governor.py        contrat et implémentation minimale du risque
src/etatmajor/strategies/{base,demo}.py
src/etatmajor/reporting/report.py     rapport JSON + résumé console
tests/conftest.py                     fixtures explicites
tests/unit/…                          12 fichiers de tests unitaires
tests/integration/…                   3 fichiers de tests d'intégration
tests/acceptance/test_cli.py          parcours complet en ligne de commande
tests/fixtures/gap_gap.csv            dataset avec gap (preuve anti-look-ahead)
artifacts/example_report.json         exemple de rapport produit
artifacts/example_journal.jsonl       exemple de journal d'audit
artifacts/nautilus_probe*.json        sortie de la sonde NautilusTrader
docs/ARCHITECTURE.md                  architecture, modèle temporel, limites
docs/ARCHITECTURE_DECISIONS.md       ADR (dont ADR-001 : NautilusTrader)
docs/PHASE2_REPORT.md                 ce rapport
docs/OPERATIONS.md                    procédures d'exploitation
docs/SECURITY.md                      sécurité et cloisonnement
docs/PROJECT_STATUS.md                état d'avancement par phase
docs/IMPLEMENTATION_PLAN.md           suite du plan
```

## 5. Commandes exécutées et résultats

```bash
# installation
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"

# suite de tests
.venv/bin/python -m pytest -q
# -> 104 passed

# validation des données
.venv/bin/python -m etatmajor.cli validate \
    --data data/sample_eurusd_1m.csv --config configs/simulation.toml
# -> 240 bar(s) acceptées, 0 erreur, 0 barre manquante

# replay
.venv/bin/python -m etatmajor.cli replay \
    --data data/sample_eurusd_1m.csv --config configs/simulation.toml \
    --report artifacts/report.json --journal artifacts/journal.jsonl
```

Résumé de la démonstration (dataset d'exemple, configuration de référence) :

```text
Strategy        : demo-lifecycle v1.0.0
Instrument      : EURUSD (1m)
Period          : 2026-01-05T00:00:00+00:00 -> 2026-01-05T03:59:00+00:00
Bars            : 240
Orders          : 2 {'FILLED': 2}
Executions      : 2 (volume 20000.0)
Fees            : 1.400000
Initial capital : 100000.00 USD
Final equity    : 100005.31 USD
Net PnL         : 5.31
End of replay   : CLOSE_AT_LAST_PRICE
Fingerprint     : f031da6bd3bd20ca
```

> Ce résultat **n'est pas** une démonstration de rentabilité. Il s'agit d'un
> cycle de vie d'ordres sur un jeu de données synthétique, destiné à vérifier
> la mécanique d'exécution. La stratégie de démonstration n'a aucune vocation
> à être rentable et n'a pas été optimisée.

## 6. Preuve de reproductibilité

Trois niveaux de preuve :

1. **Dans un processus** — `tests/integration/test_determinism.py` : deux
   replays du même dataset et de la même configuration produisent un rapport
   et un journal **identiques** (comparaison de structures, pas de chaînes).
2. **Entre processus** — même fichier de test : la commande CLI exécutée deux
   fois produit deux rapports **identiques octet pour octet**.
3. **Empreinte** — `report_fingerprint` (SHA-256 tronqué du rapport) et
   `dataset_fingerprint` identifient précisément une exécution.

Le rapport ne contient aucune information d'environnement (ni chemin absolu,
ni horodatage de génération) : c'est ce qui rend la comparaison possible d'une
machine à l'autre.

## 7. Évaluation de NautilusTrader (prototype technique préparatoire)

Installation : `nautilus_trader==1.231.0` dans un venv dédié (aucun conflit
avec l'environnement du projet, qui reste sans dépendance runtime).

Constats :

* le moteur s'installe et s'importe sur CPython 3.13 (wheel `cp313-aarch64`) ;
* le cycle backtest complet fonctionne : ordre → remplissage → position ;
* **point structurant** : sur `tests/fixtures/gap_gap.csv`, un ordre marché
  soumis pendant `on_bar` est exécuté **au cours de clôture de la bougie de
  signal** (1.10050) et non à l'ouverture de la suivante (1.11000) :

```json
"lookahead_check": {
  "signal_bar_index": 2,
  "signal_bar_close": 1.1005,
  "next_bar_open": 1.11,
  "entry_fill_price": 1.1005,
  "filled_at_signal_bar_close": true,
  "filled_at_next_bar_open": false
}
```

C'est précisément le biais que le cahier des charges interdit. Le moteur
interne applique l'inverse, vérifié par test :

```python
# tests/integration/test_replay_engine.py
assert fill["price"] == pytest.approx(1.11000)   # ouverture de la bougie suivante
assert fill["execution_bar_index"] == 3
```

Décision structurante : **ADR-001** (moteur interne pour la Phase 2,
NautilusTrader réévalué en Phase 4 pour les modèles d'exécution et le carnet
d'ordres).

## 8. Tests obligatoires : couverture

| # | Exigence | Test | Résultat |
| --- | --- | --- | --- |
| 1 | Deux replays identiques → résultats identiques | `tests/integration/test_determinism.py` (5 tests, dont comparaison inter-processus) | OK |
| 2 | Pas d'exécution sur la bougie de signal | `test_order_is_not_executed_on_the_bar_that_produced_the_signal`, `test_gap_dataset_executes_at_the_next_bar_open_not_at_the_signal_close` | OK |
| 3 | Données malformées, doublons, timestamps inversés, OHLC incohérents rejetés | `tests/unit/test_loader_validation.py` (14 tests, dont 5 cas de rejet avec numéro de ligne) | OK |
| 4 | Spread, slippage et commissions correctement appliqués | `tests/unit/test_broker.py` (spread par côté, slippage fixe et aléatoire borné, commissions par lot et forfaitaires) | OK |
| 5 | Un ordre refusé par le risque ne modifie pas le portefeuille | `test_refused_order_does_not_change_the_portfolio` (cash, position, frais, equity inchangés) | OK |
| 6 | Ordres en attente traités selon la politique de fin de replay | `test_pending_orders_are_cancelled_at_the_end_of_the_replay` | OK |
| 7 | Clôture de fin de replay conforme + comptabilité rapprochée | `test_close_at_last_price_policy_flattens_the_position`, `test_mark_to_market_policy_keeps_the_position_open`, invariants de `tests/unit/test_accounting.py` | OK |
| 8 | Fonctionnement sans réseau ni broker réel | `tests/integration/test_no_network.py` (sockets neutralisés, aucun SDK broker importé) | OK |
| 9 | Les tests préexistants continuent de réussir | suite complète : 104 tests au vert | OK |

Vérifications de valeurs (pas seulement « pas d'exception ») :

* prix d'exécution exact = ouverture de la bougie suivante + demi-spread +
  slippage ;
* commission exacte = `commission_per_lot_per_side × (quantité / lot_size) +
  commission_fixed_per_order`, par côté ;
* invariant comptable `cash == capital_initial + pnl_realise − frais` ;
* invariant `equity == cash + pnl_non_realise` ;
* invariant `pnl_net == pnl_realise + pnl_non_realise − frais` ;
* absence de double comptage des frais (test dédié).

## 9. Critères d'acceptation

| Critère | Statut | Preuve |
| --- | --- | --- |
| Les tests passent dans un environnement propre | **Satisfait** | `pip install -e ".[dev]"` puis `pytest -q` → 104 passed |
| Commandes d'installation, de test et de lancement documentées | **Satisfait** | README §1-3, `docs/OPERATIONS.md`, `scripts/run_replay.sh` |
| Tests critiques couverts par des assertions | **Satisfait** | §8 |
| Capital final et PnL cohérents | **Satisfait** | invariants de comptabilité + tests d'acceptation |
| Coûts non comptés deux fois | **Satisfait** | `test_commission_is_never_counted_twice` |
| Limites de la simulation documentées | **Satisfait** | `docs/ARCHITECTURE.md` §9, `docs/ARCHITECTURE_DECISIONS.md` |
| Aucun ordre réel envoyé | **Satisfait** | aucun SDK broker importé, aucun socket (test dédié) |
| PR détaillant fichiers, tests et risques résiduels | **Satisfait** | ce document + corps de la PR |

## 10. Limites et risques résiduels

| # | Limite | Impact | Traitement |
| --- | --- | --- | --- |
| L1 | Ambiguïté intra-bougie (stop vs cible) non résolue | biais possible sur stops | une exécution par bougie, hypothèse conservatrice ; Phase 4 (données tick ou modèle intra-bougie) |
| L2 | Swaps et financement overnight absents | PnL inexact en multi-jours | Phase 4 |
| L3 | Marge et levier non modélisés | le notionnel n'est pas contraint par la marge du broker | Phase 5 |
| L4 | Mono-instrument | pas de book multi-symboles ni d'exposition corrélée | Phase 5 |
| L5 | Format CSV uniquement, pas de Parquet ni d'ingestion MT5 | pas de pipeline de données réel | Phase 3 |
| L6 | Le rapport n'expose pas de métriques de performance (profit factor, drawdown…) | Phase 2 = moteur, pas laboratoire de performance | Phase 7/8 (`etatmajor.reporting` est l'extension naturelle) |
| L7 | Risque limité à quelques garde-fous | pas de perte journalière, drawdown, ni profil de challenge | Phase 5 |
| L8 | Interface opérateur absente (console uniquement) | pas de supervision continue | tableau de bord, phase ultérieure |
| L9 | NautilusTrader non intégré | moteur interne moins mature que le moteur candidat | réévaluation Phase 4 (ADR-001) |
| L10 | `git`/`gh` : pas de GitHub CLI sur la machine | la PR a été préparée manuellement | voir §11 |

## 11. Note de livraison (Pull Request)

La branche `feat/phase-2-replay-engine` est poussée sur
`origin`. La Pull Request vers `main` est **préparée mais non fusionnée**,
conformément à la procédure (audit du chef de projet requis).

La machine de build ne dispose pas de GitHub CLI (`gh`) ni de jeton
`GITHUB_TOKEN`. Deux voies de livraison sont donc proposées au chef de
projet :

1. **via l'API GitHub** : fournir un jeton à portée limitée
   (`repo:write` sur ce seul dépôt) et exécuter :

   ```bash
   curl -X POST -H "Authorization: Bearer $GITHUB_TOKEN" \
        -H "Accept: application/vnd.github+json" \
        https://api.github.com/repos/fortixistech-commits/EtatMajor_Sniper_EA/pulls \
        -d '{"title":"Phase 2 - deterministic replay engine","head":"feat/phase-2-replay-engine","base":"main","body":"..."}'
   ```

2. **via l'interface web** : ouvrir
   <https://github.com/fortixistech-commits/EtatMajor_Sniper_EA/compare/main...feat/phase-2-replay-engine?expand=1>
   et utiliser le corps de PR fourni en §12.

Le corps de PR est également disponible dans `docs/PR_DESCRIPTION.md`.

## 12. Contenu proposé pour la Pull Request

Voir `docs/PR_DESCRIPTION.md` (copier/coller). Il contient : résumé
d'architecture, commandes exécutées, résultats de tests, exemple de rapport,
limites restantes et statut de chaque critère d'acceptation.

## 13. Suite

Rien n'est déclaré « terminé » sur la seule présence de code. La Phase 3
(ingestion et qualité des données réelles) ne démarre qu'après validation de
la Phase 2 par le chef de projet, conformément à la procédure imposée.

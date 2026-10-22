# Architecture actuelle du dépôt

**État constaté par la MISSION 0 (2026-10-22).** Ce document décrit **ce qui
existe**, pas ce qui est prévu. La cible est décrite dans
`docs/ARCHITECTURE.md` (document de conception) et le plan de migration
figure dans `docs/audit/BACKLOG.md`.

---

## 1. Vue d'ensemble réelle

```text
                    CSV (local)
                        |
                        v
            +---------------------------+
            | etatmajor.data.loader    |  validation stricte, SHA-256,
            | etatmajor.data.validation|  rapport de qualite
            +------------+--------------+
                         | Dataset (liste de Bar)
                         v
            +---------------------------+
            | etatmajor.replay.engine  |  SimClock, ordre chronologique
            |                          |  regle anti-look-ahead
            +-----+------------+------+
                  |            |
     visible_bars |            | Signal (proposition)
                  v            v
   +--------------------+   +---------------------------+
   | strategies.base    |   | risk.governor             |
   | strategies.demo    |   | MinimalRiskGovernor       |
   | (contrat + demo)   |   | -> RiskDecision (veto)     |
   +--------------------+   +-------------+-------------+
                                            |
                                            v
                            +-------------------------------+
                            | execution.broker              |
                            | (SimulatedBroker)             |
                            | marche / limite / stop        |
                            | spread, slippage, commission |
                            +---------------+---------------+
                                            | Fill
                                            v
                            +-------------------------------+
                            | execution.accounting         |
                            | Portfolio (comptabilite)     |
                            +---------------+---------------+
                                            |
                    +-----------------------+-----------------------+
                    v                                               v
      +-----------------------------+                 +---------------------------+
      | core.journal (JSONL)        |                 | reporting.report          |
      | trace : signal, risque,     |                 | rapport JSON + resume     |
      | ordre, fill, frais          |                 | console + empreintes      |
      +-----------------------------+                 +---------------------------+

                    etatmajor.cli : validate | replay
```

## 2. Modules, responsabilités et état réel

| Module | Fichier(s) | Responsabilité | État |
| --- | --- | --- | --- |
| `core.types` | `core/types.py` | énumérations (side, type, statut, TIF, politique de fin) | complet sauf `TimeInForce` inutilisé |
| `core.errors` | `core/errors.py` | hiérarchie d'exceptions | **déclaré, jamais levé** (hors `ConfigurationError`, `DataValidationError`) |
| `core.clock` | `core/clock.py` | horloge simulée monotone | complet et testé |
| `core.events` | `core/events.py` | `Signal`, `Order`, `Fill`, `Position`, `RiskDecision` | complet ; `expires_ts_ns` non appliqué |
| `core.journal` | `core/journal.py` | journal d'événements, export JSONL | complet ; `of_type` utilisé par les tests seulement |
| `core.config` | `core/config.py` | configuration TOML validée + empreinte | complet et testé |
| `data.models` | `data/models.py` | modèle `Bar` (ns UTC) | complet (`duration_ns` inutilisé) |
| `data.validation` | `data/validation.py` | rapport de qualité | complet (`add_error` inutilisé) |
| `data.loader` | `data/loader.py` | lecture CSV, rejets motivés, empreintes | complet pour le CSV ; pas de Parquet, MT5, catalogue d'instruments ni registre de provenance |
| `execution.broker` | `execution/broker.py` | cycle de vie des ordres, modèle d'exécution | marché / limite / stop ; pas de latence, ni modification, ni fill partiel ; `quantity_step` non appliqué |
| `execution.accounting` | `execution/accounting.py` | portefeuille, PnL, frais, invariants | complet ; `notional` et `open_symbols` inutilisés |
| `replay.engine` | `replay/engine.py` | boucle de rejeu, politique de fin de replay | fonctionnel ; **copie quadratique de l'historique** (`engine.py:205`) ; `on_stop` jamais appelé |
| `risk.governor` | `risk/governor.py` | contrat d'autorisation + governor minimal | squelette : 5 garde-fous, aucune conscience du challenge |
| `strategies.base` | `strategies/base.py` | contrat `Strategy`, `StrategyContext` | complet ; `last_bars`, `close_price` inutilisés |
| `strategies.demo` | `strategies/demo.py` | stratégie de démonstration (entrée, sortie, limite non exécutable) | complète, sans vocation de rentabilité |
| `reporting.report` | `reporting/report.py` | rapport JSON + résumé console | complet ; `write_report`/`render_summary` non couverts par la couverture in-process |
| `cli` | `cli.py` | commandes `validate` et `replay` | complet |

## 3. Dépendances internes et absence de cycles

Analyse AST du graphe d'imports (`docs/audit/evidence/inventory.json →
import_graph`) : **0 dépendance circulaire**. Ordre de dépendance respecté :

```text
types < events < journal
config < clock
models < validation < loader
models < broker < accounting
models < strategies.base
config + loader + strategies + risk + execution < replay.engine < reporting
```

Le contrat de dépendance est donc **respecté** : ni `data`, ni `execution`,
ni `risk` n'importe `replay` ; `replay` n'importe que les couches inférieures.

## 4. Chemins d'exécution réellement atteignables

```text
python -m etatmajor.cli validate
  -> core.config.load_config      (validation)
  -> data.loader.load_csv         (charge + qualite)
  -> data.validation.DataQualityReport
  -> affichage console

python -m etatmajor.cli replay
  -> core.config.load_config
  -> data.loader.load_csv
  -> replay.engine.ReplayEngine.run
       -> core.clock.SimClock
       -> execution.broker.SimulatedBroker.submit / on_bar_open
       -> execution.accounting.Portfolio.apply_fill
       -> strategies.base.StrategyContext  (visible_bars)
       -> strategies.demo.DemoLifecycleStrategy.on_bar
       -> risk.governor.MinimalRiskGovernor.authorize
       -> core.journal.Journal.append
       -> fin de replay : annulation + cloture
  -> reporting.report.build_report -> write_report / render_summary
```

**Chemins non atteignables / non existants :**

| Chemin attendu | État |
| --- | --- |
| `ChallengeEngine` / profil de challenge | inexistant |
| Sniper Engine / détecteur de régime | inexistant |
| Mission Planner / `MissionPlan` | inexistant |
| Position Monitor | inexistant |
| Cockpit | inexistant |
| Adaptateur MT5 (lecture) | inexistant |
| Performance Lab (métriques, walk-forward) | inexistant |
| Envoi d'ordre réel | **techniquement impossible** (aucun import réseau, aucun SDK broker) |

## 5. Modèle temporel appliqué

```text
ts_open(i)   : execution des ordres acceptes a la cloture de i-1
ts_close(i)  : la bougie est visible ; strategies.base.StrategyContext
               est construit avec visible_bars = bars[0..i]
               (copie complete : cout quadratique, cf. AUDIT-D1)
```

| Garantie | Mécanisme | Test |
| --- | --- | --- |
| Pas de fuite temporelle | `visible_bars` tronqué à `index + 1` | `test_strategy_cannot_observe_future_bars` |
| Exécution sur la bougie suivante | exécution à l'ouverture de `i+1` | `test_order_is_not_executed_on_the_bar_that_produced_the_signal` |
| Comportement correct sur gap | prix = ouverture après gap | `test_gap_dataset_executes_at_the_next_bar_open_not_at_the_signal_close` |
| Reproductibilité | graine fixe, horloge simulée, rapport sans horodatage mur | 5 tests de `test_determinism.py` |

## 6. Persistance et traçabilité

| Élément | Support | Limite |
| --- | --- | --- |
| Journal d'événements | `artifacts/journal.jsonl` (JSONL) | non rejouable : pas de commande de reprise |
| Rapport de campagne | `artifacts/report.json` | reconstruit depuis l'état du moteur, pas depuis le journal |
| Empreinte de dataset | SHA-256 du fichier + empreinte du contenu | aucun registre versionné des datasets |
| Empreinte de configuration | SHA-256 tronqué de la configuration effective | pas de version lisible |
| Données sources | fichiers CSV dans `data/` | pas de copie immuable contrôlée |

## 7. Points de friction relevés (résumé)

1. **copie quadratique** de l'historique visible (`replay/engine.py:205`) ;
2. **cycle de vie incomplet** : `on_stop` jamais appelé ;
3. **expiration de signal** déclarée mais non appliquée ;
4. **`quantity_step`** configuré mais non appliqué par le broker ;
5. **`mode`** codé en dur dans le rapport ;
6. **exceptions typées** jamais levées, `except Exception` dans le moteur ;
7. **API morte** : 9 symboles publics jamais référencés ;
8. **fingerprint** recalculé trois fois par campagne ;
9. **détection de trous** approximative ;
10. **absence de catalogue d'instruments** et de **registre de provenance**.

Le détail, la preuve et le correctif proposé de chacun de ces points
figurent dans `docs/audit/INITIAL_AUDIT.md` (§6) et
`docs/audit/BACKLOG.md`.

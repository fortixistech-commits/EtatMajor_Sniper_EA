# État du projet

**Projet :** ETAT-MAJOR SNIPER EA
**Date :** 2026-10-22
**Phase courante :** MISSION 0 (audit) livrée, en attente d'audit du chef de projet

---

## 1. Tableau d'avancement

| Phase | Objet | Statut | Preuve |
| --- | --- | --- | --- |
| MISSION 0 | Audit factuel du dépôt (nouvelle feuille de route) | **Terminée** | `docs/audit/INITIAL_AUDIT.md`, `docs/architecture/CURRENT_ARCHITECTURE.md`, `docs/audit/BACKLOG.md`, preuves dans `docs/audit/evidence/` et `tests/results/2026-10-22-mission-0/` |
| Phase 0 | Audit du dépôt et préparation | **Terminée** | ce document, `docs/ARCHITECTURE_DECISIONS.md`, `docs/SECURITY.md` |
| 1 | Squelette logiciel et contrats | **Terminée** | `src/etatmajor/**`, `pyproject.toml`, `configs/` |
| 2 | Prototype du moteur de simulation | **Terminée** | `docs/PHASE2_REPORT.md`, 104 tests, rapport d'exemple versionné |
| 3 | Ingestion et qualité des données de marché | À faire | — |
| 4 | Replay historique et modèle d'exécution | À faire | — |
| 5 | Moteur de risque et challenge prop firm | À faire | — |
| 6 | Doctrine Sniper et interface des stratégies | À faire | — |
| 7 | Évaluation du comportement et stress | À faire | — |
| 8 | Backtests, robustesse, sélection | À faire | — |
| 9 | Adaptateur MT5 et paper trading | À faire | — |
| 10 | Préparation et activation de la production | À faire | — |

## 2. Environnement de référence

| Élément | Valeur |
| --- | --- |
| Python | 3.13.7 |
| Plateforme | Linux aarch64 |
| Moteur de replay | moteur interne `etatmajor.replay` (zéro dépendance runtime) |
| Moteur candidat évalué | NautilusTrader 1.231.0 (venv isolé, `scripts/probe_nautilus.py`) |
| Tests | pytest, 104 tests au vert |

## 3. Capacités disponibles

* rechargement déterministe de données OHLC avec validation et rapport de
  qualité ;
* horloge simulée, ordre chronologique garanti, absence de fuite temporelle ;
* contrat de stratégie (proposition structurée ou abstention explicite) ;
* broker simulé (marché, limite, stop) avec spread, slippage, commissions et
  rejets ;
* comptabilité du portefeuille avec invariants testés ;
* autorité de risque injectable avec droit de veto et journalisation des
  refus ;
* politique de fin de replay explicite ;
* journal d'événements JSONL et rapport JSON reproductible ;
* interface en ligne de commande (validation, replay, rapport, journal).

## 4. Capacités absentes (par construction)

* aucun envoi d'ordre réel, aucune connexion broker ;
* aucune ingestion de données réelles MT5 (Phase 3) ;
* aucune métrique de performance (Phase 7/8) ;
* aucune politique de challenge prop firm (Phase 5) ;
* aucun tableau de bord opérateur ;
* aucune intégration MQL5/MT5 (Phase 9).

## 5. Décisions en attente de validation

| ADR | Décision | Attente |
| --- | --- | --- |
| ADR-001 | moteur interne pour la Phase 2, NautilusTrader réévalué en Phase 4 | arbitrage du chef de projet |
| ADR-002 | exécution à l'ouverture de la bougie suivante | arbitrage du chef de projet |
| ADR-003 | quantités en unités instrument, `lot_size` configurable | arbitrage du chef de projet |
| ADR-004 | politique de fin de replay explicite | arbitrage du chef de projet |
| ADR-005 | rapport sans donnée d'environnement | arbitrage du chef de projet |
| ADR-006 | le journal est la source de vérité de l'audit | arbitrage du chef de projet |

## 6. Resultat de la MISSION 0 (audit)

Conformite mesuree contre les missions du CDC :

| Mission | Conformite | Constat principal |
| --- | --- | --- |
| Mission 1 - socle et contrats | ~55 % | modeles `MissionPlan`, `TradeIntent`, `AccountState`, `ChallengeState` absents ; modes non parametrables |
| Mission 2 - replay deterministe | ~80 % | fonctionnel mais **quadratique** (114 us/bougie a 20 000 bougies) |
| Mission 3 - donnees | ~30 % | CSV seul, pas de catalogue d'instruments ni de registre de provenance |
| Mission 4 - execution simulee | ~50 % | pas de latence, ni de fills partiels, ni d'alignement sur le pas de volume |
| Missions 5 a 16 | absentes | RiskGovernor squelette, aucun Challenge Engine, aucun Sniper Engine, aucun cockpit, aucun adaptateur MT5 |

Defauts majors : AUDIT-D1 (rejeu quadratique), AUDIT-D10 (pas de catalogue
d'instruments), AUDIT-D11 (socle challenge absent), AUDIT-D12 (RiskGovernor
sans conscience du challenge).

Ordre de correction propose : **C1 -> C2 -> C3** (corrections du socle, sans
nouvelle capacite), puis C4 (contrats), C5 (instruments et provenance),
C6 (Challenge Engine The5ers), C7 (RiskGovernor conscient du challenge),
C8 (Sniper Engine), C9 (Performance Lab).

## 7. Blocages

* **Aucun blocage technique** pour les Phases 3 et 4.
* **Livraison de la PR** : la machine ne dispose ni de GitHub CLI, ni de clé
  SSH, ni de jeton d'API. `git push` échoue sur
  `could not read Username for 'https://github.com'`. La branche
  `feat/phase-2-replay-engine` (9 commits au-dessus de `main`) est **locale**
  et un bundle de transfert est produit (`git bundle create
  ../EtatMajor_Sniper_EA_phase2.bundle main feat/phase-2-replay-engine`).
  La procédure de push et d'ouverture de PR (3 voies) est décrite en §11 du
  rapport de phase.

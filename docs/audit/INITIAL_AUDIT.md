# MISSION 0 — Audit factuel du dépôt

**Projet :** ÉTAT-MAJOR SNIPER EA
**Dépôt :** `fortixistech-commits/EtatMajor_Sniper_EA`
**Branche d'audit :** `feat/mission-0-audit` (base : `feat/phase-2-replay-engine`)
**Date :** 2026-10-22
**Auteur :** ingénieur logiciel
**Statut :** VALIDÉ POUR REVUE

> Aucune modification fonctionnelle n'a été apportée pendant cette mission. Les
> seuls ajouts sont l'outillage d'audit, les preuves d'exécution et les
> documents de cadrage. Aucun ordre réel n'est possible : le dépôt ne contient
> aucune capacité réseau (vérifié, §5).

---

## 1. Méthode

L'audit s'appuie sur des **preuves exécutables**, pas sur la lecture du code
seule. Trois sources de preuve sont versionnées :

| Preuve | Fichier | Contenu |
| --- | --- | --- |
| Inventaire statique | `docs/audit/evidence/inventory.json` | 39 fichiers Python, 4 625 lignes, graphe d'imports, stubs, symboles morts |
| Exécution des tests | `tests/results/2026-10-22-mission-0/` | sortie console `-v`, `junit.xml`, rapport de couverture, exécution de couverture |
| Mesure de performance | `docs/audit/evidence/benchmark.json`, `profile-10k-bars.txt` | temps de rejeu, débit, mémoire, profil `cProfile` |

Commandes d'audit reproductibles :

```bash
python scripts/audit_inventory.py --output docs/audit/evidence
python scripts/benchmark_replay.py --output docs/audit/evidence
python -m pytest -v --junitxml=tests/results/<date>/junit.xml
python -m coverage run --source=src/etatmajor -m pytest -q
python -m coverage report -m
```

---

## 2. État initial du dépôt

| Élément | Constat | Preuve |
| --- | --- | --- |
| Dépôt GitHub | créé, **vide** (aucun commit) à l'ouverture de la mission | `git log` avant amorçage |
| Historique | inexistant → aucun fichier existant supprimé ou réécrit | arbre git |
| Commits actuels | 10 (`main` : 1 fondation ; `feat/phase-2-replay-engine` : 9) | `git log --oneline --all` |
| Langage | Python 3.11+ (validé 3.13.7), 39 fichiers, 4 625 lignes | `inventory.json` |
| Dépendances runtime | **aucune** (bibliothèque standard uniquement) | `pip list` du venv propre : `etatmajor-sniper-ea` + pytest |
| Points d'entrée | `etatmajor.cli:main` (`python -m etatmajor.cli validate|replay`) | `pyproject.toml` |
| Configuration | 2 fichiers TOML (`configs/simulation.toml`, `configs/risk.toml`) | `configs/` |
| Scripts | 4 (génération de données, rejeu, sonde NautilusTrader ×2) | `scripts/` |
| Tests | 104 tests, 6 fichiers, 3 niveaux (unit / intégration / acceptation) | `junit.xml` |
| CI | workflow GitHub Actions (Python 3.11/3.12/3.13 + contrôle de reproductibilité) | `.github/workflows/ci.yml` |
| Documentation | 11 documents (architecture, ADR, rapport de phase, opérations, sécurité, statut, plan, PR) | `docs/` |

### 2.1 Blocage de livraison (non résolu)

La machine ne dispose **ni de GitHub CLI, ni de clé SSH, ni de jeton d'API**.
`git push` échoue sur `could not read Username for 'https://github.com'`.
La branche `feat/phase-2-replay-engine` **n'est donc pas sur GitHub** et la
Pull Request de la Phase 2 **n'a pas été ouverte**. Le rapport de Phase 2
(documents cette limite) et le présent audit la maintiennent explicitement.

**Procédure de livraison prête à l'emploi** (`scripts/push_branches.sh`) :
elle utilise un jeton fourni par l'environnement `GITHUB_TOKEN` via
`GIT_ASKPASS`, de sorte que le jeton n'apparaît ni dans la ligne de commande,
ni dans `.git/config`, ni dans les journaux.

```bash
export GITHUB_TOKEN=<jeton repo:write sur ce seul dépôt>
./scripts/push_branches.sh
```

Le script pousse `main`, `feat/phase-2-replay-engine` et `feat/mission-0-audit`,
afin de permettre une Pull Request par phase (Phase 2, puis MISSION 0).

---

## 3. Inventaire des modules et de leurs dépendances

Graphe d'imports internes (extrait de `inventory.json`, `import_graph`) :

```text
core.types ◄── core.events ◄── core.journal
core.config ◄── core.clock
     │
     ▼
data.models ── data.validation ── data.loader
     │                              │
     ▼                              ▼
strategies.base              execution.broker ── execution.accounting
     │                              │                  │
     └──────────► replay.engine ◄──┴──────────────────┘
                        │
                        ▼
                 reporting.report ──► core.journal
```

| Module | Fichiers | Lignes | Rôle | Statut |
| --- | --- | --- | --- | --- |
| `etatmajor.core` | 6 | 461 | horloge, types, erreurs, événements, journal, configuration | **fonctionnel** (2 réserves) |
| `etatmajor.data` | 3 | 204 | modèle de bougie, chargement CSV, rapport de qualité | **partiel** |
| `etatmajor.execution` | 2 | 224 | broker simulé, comptabilité du portefeuille | **partiel** |
| `etatmajor.replay` | 1 | 483 | moteur de replay, politique de fin de replay | **fonctionnel** (1 défaut majeur) |
| `etatmajor.risk` | 1 | 100 | contrat + governor minimal | **simulé** (squelette) |
| `etatmajor.strategies` | 2 | 71 | contrat de stratégie + stratégie de démonstration | **partiel** |
| `etatmajor.reporting` | 1 | 181 | rapport JSON + résumé console | **partiel** |
| `etatmajor.cli` | 1 | 149 | commandes `validate` / `replay` | **fonctionnel** |

**Dépendances circulaires : 0** (vérifié par analyse AST du graphe d'imports).
**Fonctions vides / stubs : 0**. **Marqueurs TODO/FIXME : 1** (motif `pass` dans
la documentation, sans effet).

---

## 4. Résultat des tests existants

```
104 passed in 2.67s
```

| Niveau | Fichier | Tests | Couverture du module visé |
| --- | --- | --- | --- |
| Unitaire | `tests/unit/test_accounting.py` | 9 | invariants comptables (cash, equity, PnL net, non-double comptage) |
| Unitaire | `tests/unit/test_broker.py` | 13 | spread par côté, slippage, commissions, rejets, limite/stop, gap, déterminisme |
| Unitaire | `tests/unit/test_clock.py` | 5 | horloge simulée |
| Unitaire | `tests/unit/test_config.py` | 13 | validation de configuration, TOML, empreintes |
| Unitaire | `tests/unit/test_loader_validation.py` | 14 | rejets de données avec numéro de ligne |
| Unitaire | `tests/unit/test_risk_governor.py` | 8 | refus du risque, limites |
| Intégration | `tests/integration/test_replay_engine.py` | 13 | cycle de vie, anti-look-ahead, refus, fin de replay |
| Intégration | `tests/integration/test_determinism.py` | 5 | reproductibilité, y compris inter-processus |
| Intégration | `tests/integration/test_no_network.py` | 3 | isolation réseau et absence de SDK broker |
| Acceptation | `tests/acceptance/test_cli.py` | 4 | parcours CLI complet, rapport de référence |

Couverture globale : **86 %** des instructions de `src/etatmajor`
(`tests/results/2026-10-22-mission-0/coverage-report.txt`).

Points de couverture faibles, à traiter :

| Module | Couverture | Cause |
| --- | --- | --- |
| `cli.py` | 0 % | exercé par sous-processus dans les tests d'acceptation : la couverture ne voit pas le code des sous-processus |
| `reporting/report.py` | 77 % | `write_report` et `render_summary` non couverts en processus |
| `strategies/base.py` | 80 % | accesseurs déclarés mais jamais utilisés (voir AUDIT-D7) |
| `core/errors.py` | 85 % | exceptions déclarées jamais levées (AUDIT-D6) |
| `replay/engine.py` | 94 % | branche d'exception du `on_bar` et branche de refus du broker à la clôture finale |

---

## 5. Vérification « aucun ordre réel possible »

| Contrôle | Résultat | Preuve |
| --- | --- | --- |
| Import de `socket`, `requests`, `urllib`, `http`, `MetaTrader5` dans `src/` | **0 occurrence** | `grep -rnE "import (socket\|requests\|urllib\|http\|MetaTrader5)" src/` |
| Test d'exécution avec sockets neutralisés | **réussi** | `tests/integration/test_no_network.py::test_replay_runs_with_networking_disabled` |
| Test d'absence de SDK broker importé | **réussi** | `test_the_package_does_not_import_any_broker_library` |
| Adaptateur broker réel | **inexistant** | aucun module `mt5`/`execution/adapters` |

**Conclusion : le dépôt ne peut pas envoyer d'ordre réel.** La séparation
LAB / CHALLENGE_SIM / PAPER (Mission 1) reste à faire, mais elle n'est pas
urgente sur le plan de la sécurité immédiate : aucun chemin d'exécution vers
un broker n'existe.

---

## 6. Défauts et écarts identifiés

Gravité : **Majeure** = bloque une porte de validation ou produit un résultat
faux · **Mineure** = contrat incomplet ou code mort · **Absence** = composant
manquant par rapport à la feuille de route.

### AUDIT-D1 — Rejeu quadratique (MAJEURE)

**Preuve :** `docs/audit/evidence/benchmark.json`

| Bougies | Temps de rejeu | µs / bougie |
| --- | --- | --- |
| 240 | 0,010 s | 43,0 |
| 5 000 | 0,197 s | 39,3 |
| 10 000 | 0,662 s | 66,2 |
| 20 000 | 2,285 s | **114,2** |

Le coût par bougie croît linéairement avec le nombre de bougies, donc le
temps total croît **quadratiquement**. Profil `cProfile`
(`profile-10k-bars.txt`) : `_process_bar_close` = 0,515 s sur 0,846 s, dont
0,395 s d'exécution propre.

**Cause racine :** `src/etatmajor/replay/engine.py:205`

```python
visible_bars=tuple(self.dataset.bars[: index + 1]),
```

À chaque bougie, le moteur **recopie l'intégralité de l'historique visible**
pour garantir l'absence de fuite temporelle. Mesure isolée : 20 000 copies
progressives = 6,49 s.

**Impact projeté :** 100 000 bougies (70 jours de M1) ≈ 57 s ; 1 000 000
bougies (2 ans de M1) ≈ 95 minutes pour un seul rejeu. Une campagne de
validation (walk-forward, Monte-Carlo, sensibilité) exige des centaines de
rejeux : le simulateur est **inutilisable en l'état** aux volumes exigés par
les Missions 12 et 13.

**Ce défaut ne remet pas en cause la règle anti-look-ahead** (elle est
correcte) mais son implémentation. Correction proposée : exposer une vue
bornée (`VisibleBars`) au lieu d'une copie, avec `__len__` O(1) et accès par
index. Vérifiable par un test d'invariant (aucune barre future visible) qui
doit rester vert.

### AUDIT-D2 — Le cycle de vie de la stratégie n'est pas complet (MINEURE)

**Preuve :** `grep -rn "on_stop" src/` → seules les définitions existent
(`strategies/base.py:71`, `strategies/demo.py:93`). Le moteur appelle
`on_start` (`replay/engine.py:124`) et `on_bar` (`:211`) mais **jamais
`on_stop`**.

**Impact :** une stratégie ne peut pas clôturer proprement (annuler ses
ordres, clôturer ses positions, journaliser son bilan de fin de campagne).
Le contrat documente un comportement que le moteur n'exécute pas.

### AUDIT-D3 — `Signal.expires_ts_ns` n'est jamais appliqué (MINEURE)

**Preuve :** `core/events.py:36` déclare le champ ; aucune occurrence dans
`replay/engine.py`. Un signal expiré reste exécutable.

**Impact :** une stratégie qui émet un signal à durée de vie limitée peut
être exécutée après expiration. Contredit l'exigence « conditions
d'annulation » de la doctrine.

### AUDIT-D4 — `quantity_step` configuré mais jamais appliqué (MINEURE)

**Preuve :** `core/config.py:103` déclare le pas de volume ;
`execution/broker.py:90-105` (contrôle pré-trade) vérifie `min_quantity` et
`max_quantity` **mais pas l'alignement sur le pas**.

**Impact :** une quantité non alignée (0,015 lot sur un pas de 0,01) est
acceptée par le broker simulé alors qu'elle serait refusée par un broker
réel. Divergence simulation / réalité non documentée.

### AUDIT-D5 — `mode` codé en dur (MINEURE)

**Preuve :** `reporting/report.py:62` → `"mode": "LABORATORY"` littéral.
Aucun énumérateur de mode, aucun contrôle de cohérence entre le mode déclaré
et le comportement.

**Impact :** la Mission 1 exige `LAB` / `CHALLENGE_SIM` / `PAPER` avec
interdiction de passage silencieux. Le rapport *affiche* un mode, mais il
n'est ni paramétrable ni vérifié.

### AUDIT-D6 — Contrat d'erreurs déclaré mais non appliqué (MINEURE)

**Preuve :** `inventory.json → exceptions_never_raised` =
`['EtatMajorError', 'ExecutionError', 'RiskRejected', 'StrategyError']`.
Le moteur intercepte `except Exception` (`replay/engine.py:125` et `:212`) et
remonte une `ValueError` brute.

**Impact :** une stratégie qui viole son contrat produit une `ValueError`
géométrique au lieu de `StrategyError` ; l'appelant ne peut pas distinguer
une faute de l'opérateur d'une faute de la stratégie.

### AUDIT-D7 — Surface d'API morte (MINEURE)

**Preuve :** `inventory.json → unreferenced_symbols` (13 symboles, hors
tests) :

| Symbole | Fichier | Statut |
| --- | --- | --- |
| `TimeInForce` | `core/types.py:50` | aucun ordre ne porte de time-in-force |
| `Portfolio.notional()` | `execution/accounting.py:146` | jamais appelé |
| `Portfolio.open_symbols()` | `execution/accounting.py:140` | jamais appelé |
| `Bar.duration_ns` | `data/models.py:35` | jamais appelé |
| `DataQualityReport.add_error()` | `data/validation.py:31` | jamais appelé |
| `StrategyContext.last_bars()` | `strategies/base.py:43` | jamais appelé |
| `StrategyContext.close_price()` | `strategies/base.py:39` | doublon de `.close` |
| `OrderSide.opposite` | `core/types.py:22` | jamais appelé |
| `RiskRejected`, `ExecutionError`, `StrategyError` | `core/errors.py` | jamais levés |

**Impact :** un contrat annoncé mais non exercé donne une impression de
couverture fonctionnelle qui n'existe pas. `TimeInForce` en particulier
laisse croire à une gestion des ordres expirés inexistante.

### AUDIT-D8 — Fingerprint de dataset recalculé trois fois (MINEURE)

**Preuve :** `profile-10k-bars.txt` → `data/loader.py:96(fingerprint)` appelé
3 fois pour 0,134 s sur 10 000 bougies (O(n) à chaque fois).

**Impact :** sur un dataset de 1 M de bougies, ~0,5 s par fingerprint, répété
à chaque rapport. Sans gravité, mais à corriger avec AUDIT-D1.

### AUDIT-D9 — Détection de trous approximative (MINEURE)

**Preuve :** `data/loader.py` (section « Gap detection ») : l'écart est
calculé entre le premier et le dernier timestamp divided par le timeframe.
Un dataset à timestamps irréguliers (pas aligné sur la grille) produit un
compte de trous faux, et une absence de cotation normale (week-end, session
fermée) est indiscernable d'une perte de données.

**Impact :** la Mission 3 exige de distinguer « absence de cotation normale »
et « défaillance du fournisseur ». Aujourd'hui les deux sont indiscernables.

### AUDIT-D10 — Absence de catalogue d'instruments (MAJEURE pour la Mission 3)

Aucun module `instruments` : les décimales, le lot size, le tick value, les
volumes min/max, le pas de volume, les horaires, les swaps et les commissions
par broker ne sont pas modélisés. `lot_size` est un paramètre global de la
configuration d'exécution (`core/config.py:102`), pas une propriété d'un
instrument.

**Impact :** le simulateur ne peut pas garantir la fidélité d'exécution
demandée par la Porte G4 (fidélité opérationnelle) ni reproduire les règles
d'un broker The5ers réel.

### AUDIT-D11 — Absence de tout le socle « challenge » (ABSENCE)

| Attendu (Mission 5/6/7) | Présent ? |
| --- | --- |
| `ChallengeProfile`, `ChallengeState`, `ChallengeEngine` | **non** (0 définition) |
| `MissionPlan`, `TradeIntent` | **non** |
| `AccountState`, `PortfolioState` | **non** (seul `PortfolioSnapshot` existe) |
| `MarketSnapshot`, `MarketTick`, `OrderResult` | **non** |
| `ExecutionEvent`, `AuditEvent` | **non** (`JournalEntry` joue un rôle voisin) |
| Détecteur de régime, Sniper Engine, Mission Planner | **non** |
| Position Monitor | **non** |
| Cockpit | **non** |
| Adaptateur MT5 | **non** |
| Performance Lab (métriques, walk-forward, Monte-Carlo) | **non** |

`configs/prop_firms/` existe mais est **vide** (dossier non suivi par git) :
la structure annonce une capacité qui n'est pas là.

### AUDIT-D12 — RiskGovernor sans conscience du challenge (ABSENCE)

**Preuve :** `risk/governor.py:60-100` : les seuls contrôles sont
`trading_halted`, quantité, notionnel, nombre de positions ouvertes.

**Impact :** aucune perte journalière, aucun drawdown, aucune règle The5ers.
La Porte G2 (sécurité) ne peut pas être franchie. C'est la raison pour
laquelle le simulateur actuel ne peut pas répondre à la question centrale du
produit : « aurions-nous respecté les règles du challenge ? ».

---

## 7. Matrice de conformité par mission

Statuts : **fonctionnel** / **partiel** / **simulé** / **absent** / **défectueux**.

### Mission 1 — Socle logiciel et contrats

| Exigence | Statut | Preuve / écart |
| --- | --- | --- |
| Modèles `MarketBar`, `MarketTick`, `MarketSnapshot` | partiel | `MarketBar` = `data/models.py:Bar` ; tick et snapshot **absents** |
| `TradingSignal` | fonctionnel | `core/events.py:Signal` |
| `TradeIntent`, `MissionPlan` | absent | AUDIT-D11 |
| `OrderRequest`, `OrderResult` | partiel | `OrderRequest` existe (`risk/governor.py`), `OrderResult` absent |
| `Position`, `AccountState`, `PortfolioState` | partiel | `Position` existe ; `AccountState`/`PortfolioState` absents |
| `RiskDecision` | fonctionnel | `core/events.py` |
| `ChallengeState` | absent | AUDIT-D11 |
| `ExecutionEvent`, `AuditEvent` | partiel | `JournalEntry` couvre le journal, pas les événements d'exécution typés |
| Interfaces data / strategy / risque / broker / challenge | partiel | 4 interfaces sur 5 ; challenge absent |
| Séparation `LAB` / `CHALLENGE_SIM` / `PAPER` | absent | AUDIT-D5 |
| Configuration validée au démarrage | fonctionnel | `core/config.py`, 13 tests |
| Identifiants session / ordre / stratégie / version de config | partiel | `order_id` et `client_order_id` existent ; session et version de configuration absents |
| Journalisation structurée centralisée | fonctionnel | `core/journal.py` |
| Règles dates / fuseaux / devises / décimaux | partiel | timestamps UTC ns ; mais pas de devise par instrument ni de politique de décimaux |
| Interdiction des dépendances circulaires | **satisfait** | 0 cycle détecté |
| Refus d'une configuration incohérente au démarrage | fonctionnel | `AppConfig.validate()` |

**Verdict Mission 1 : partiel (~55 %).**

### Mission 2 — Moteur de replay déterministe

| Exigence | Statut | Preuve / écart |
| --- | --- | --- |
| Chargement de séries OHLCV horodatées | fonctionnel | `data/loader.py` |
| Tri, doublons, trous, incohérences | fonctionnel (trous approximatifs) | AUDIT-D9 |
| Convention temporelle des bougies | fonctionnel | `open_ns` / `close_ns` explicites |
| Exposition des seules informations disponibles | fonctionnel | `visible_bars` + test `test_strategy_cannot_observe_future_bars` |
| Horloge simulée | fonctionnel | `core/clock.py`, 5 tests |
| Ordre des événements à horodatage identique | partiel | règle « ordre de soumission » documentée mais non testée spécifiquement |
| Arrêt / reprise / exécution par fenêtre | absent | aucun mécanisme de reprise |
| Journal permettant de rejouer une session | fonctionnel | `journal.jsonl` |
| Identifiant de dataset et empreinte de configuration | fonctionnel | `dataset.fingerprint()`, `config.fingerprint()` |
| Tests de déterminisme | **satisfait** | 5 tests, dont comparaison inter-processus |
| Absence de fuite de données futures | **satisfait** | test sur dataset avec gap |
| Fichier corrompu signalé explicitement | fonctionnel | `DataValidationError` avec lignes fautives |
| Statistiques recalculables depuis le journal | partiel | le rapport est reconstruit depuis l'état moteur, pas depuis le journal |

**Verdict Mission 2 : partiel (~80 %), avec un défaut majeur (AUDIT-D1).**

### Mission 3 — Collecte et qualité des données

| Exigence | Statut | Preuve / écart |
| --- | --- | --- |
| Format d'importation | fonctionnel | CSV uniquement |
| Normalisation (noms, horodatages, prix, volumes, unités) | partiel | horodatages UTC ns ; pas de catalogue d'instruments (AUDIT-D10) |
| Contrôles de valeurs manquantes / doublons / malformations / ruptures | fonctionnel | 14 tests, numéro de ligne |
| Distinguer absence de cotation et défaillance fournisseur | absent | AUDIT-D9 |
| Calendriers de marché, sessions, changements d'heure, jours fériés | absent | — |
| Registre des sources, dates, transformations, empreintes | partiel | SHA-256 + empreinte de contenu dans le rapport, mais **aucun registre** versionné |
| Copie immuable des données sources | partiel | le fichier source est conservé, mais rien n'en interdit la modification |
| Contrôles spécifiques aux instruments du challenge | absent | AUDIT-D10 |
| Interface commune historique / live | absent | — |
| Interdiction d'utiliser un dataset dont les contrôles critiques échouent | fonctionnel | `strict=True` par défaut |

**Verdict Mission 3 : partiel (~30 %).**

### Mission 4 — Moteur d'exécution simulée

| Exigence | Statut | Preuve / écart |
| --- | --- | --- |
| Types d'ordres | partiel | marché / limite / stop ; **pas de modification ni de fermeture partielle** |
| Ouvertures, clôtures, rejets | fonctionnel | `execution/broker.py`, 13 tests |
| Spread, commission, slippage, latence | partiel | spread, commission, slippage présents ; **latence absente** |
| Gaps et mouvements entre deux observations | partiel | gap géré pour les stops ; pas de modèle de gap de marché |
| Positions partielles, arrondis instrument | absent | fills 100 % ; `quantity_step` non appliqué (AUDIT-D4) |
| Hypothèse intra-bougie stop/take-profit | fonctionnel (documentée, conservatrice) | `docs/ARCHITECTURE.md` §4 |
| PnL réalisé, latent, frais, equity | fonctionnel | 9 tests d'invariants |
| Réconciliation ordres / transactions / positions | partiel | le journal retrace la chaîne, mais aucune **réconciliation automatique** ne compare journal et portefeuille |
| Journal d'exécution complet | fonctionnel | `journal.jsonl` |
| Scénarios de rejet, slippage défavorable, indisponibilité | partiel | rejet probabiliste et slippage paramétrables ; pas de scénario d'indisponibilité |

**Verdict Mission 4 : partiel (~50 %).**

### Missions 5 à 16 — absentes

| Mission | Statut | Commentaire |
| --- | --- | --- |
| 5 — RiskGovernor | simulé | contrat + 5 garde-fous ; aucun challenge, aucun kill switch persistant |
| 6 — Sniper Engine | absent | aucun détecteur de régime, aucune famille de setup |
| 7 — Challenge Engine | absent | aucun profil, aucun état PASSED/FAILED |
| 8 — Connecteur MT5 | absent | aucun adaptateur |
| 9 — Cockpit | absent | console uniquement |
| 10 — Environnement intégré | absent | pas de campagne de bout en bout |
| 11 — Audit indépendant | absent | le présent document est l'audit initial, pas l'audit indépendant de la Mission 11 |
| 12 — Optimisation robuste | absent | bloqué en partie par AUDIT-D1 |
| 13 — Paper trading | absent | — |
| 14 — Évaluation réelle | absent | **hors périmètre tant que G1..G5 ne sont pas franchies** |
| 15 — Montée en charge | absent | — |
| 16 — Intelligence adaptative | absent | — |

---

## 8. Choix technologique : Python, Numba, Rust, MQL5

La feuille de route impose de ne recourir à un langage natif qu'**après
mesure** d'un goulot d'étranglement réel. Mesure
(`docs/audit/evidence/benchmark.json`) :

| Profil | Bougies | Rejeu | Débit | RSS |
| --- | --- | --- | --- | --- |
| exemple | 240 | 0,010 s | 23 231 /s | 19,5 Mo |
| travail | 5 000 | 0,197 s | 25 429 /s | 21,2 Mo |
| important | 20 000 | 2,285 s | 8 753 /s | 26,1 Mo |

Décision, argumentée :

| Technologie | Décision | Justification |
| --- | --- | --- |
| **Python** | **conservée** | 1,14 k instructions, 86 % de couverture, 104 tests. Le goulot mesuré est **algorithmique** (AUDIT-D1), pas un problème d'interpréteur. |
| **Numba** | **écartée pour l'instant** | Le calcul pur (P&L, commissions) représente une fraction marginale du temps : le goulot est l'allocation mémoire de la copie d'historique. Numba n'agirait pas dessus. À réévaluer **après** correction d'AUDIT-D1. |
| **Rust** | **écartée pour l'instant** | Aucun besoin démontré : 8 700 à 25 000 bougies/s suffisent à un rejeu historique. Un port Rust du moteur serait justifié si, après correction d'AUDIT-D1, le débit остаit insuffisant pour une campagne de Monte-Carlo (à chiffrer). |
| **MQL5** | **non utilisé** | Aucun composant actuel ne doit résider dans MT5. MQL5 ne sera introduit qu'au moment de l'adaptateur MT5 (Mission 8), et **en lecture seule** : l'ordre réel restera interdit (Mission 8, exigence 7). |

**Conclusion :** le goulot est une **erreur d'implémentation**, pas un
limite de langage. Le correctif est en Python pur et doit précéder toute
discussion Rust/Numba.

---

## 9. Risques techniques classés par gravité

| # | Risque | Gravité | Impact | Traitement proposé |
| --- | --- | --- | --- | --- |
| R1 | Rejeu quadratique (AUDIT-D1) | **majeure** | campagnes de validation inexécutables | correction C1, prioritaire |
| R2 | Pas de Challenge Engine (D11/D12) | **majeure** | le produit ne peut pas répondre à la question centrale | mission 7, prioritaire après C1/C2 |
| R3 | Pas de catalogue d'instruments (D10) | **majeure** | fidélité d'exécution non garantie (Porte G4) | mission 3 |
| R4 | Cycle de vie de stratégie incomplet (D2) | mineure | pas de clôture propre de campagne | correction C2 |
| R5 | Signaux expirables non appliqués (D3) | mineure | exécution de signaux périmés | correction C2 |
| R6 | Pas de quantité alignée sur le pas (D4) | mineure | divergence avec un broker réel | correction C3 |
| R7 | Modes non paramétrables (D5) | mineure | pas de séparation LAB/PAPER (Mission 1) | correction C3 |
| R8 | Contrat d'erreurs non appliqué (D6/D7) | mineure | diagnostic dégradé, API morte | correction C3 |
| R9 | Détection de trous approximative (D9) | mineure | confusion cotation normale / perte de données | mission 3 |
| R10 | Branches non poussées sur GitHub (§2.1) | **majeure** | pas de revue possible | action humaine : push + PR |

---

## 10. Backlog des écarts et ordre de correction proposé

Le détail est dans `docs/audit/BACKLOG.md`. Ordre proposé :

| Rang | Correction | Raison | Taille |
| --- | --- | --- | --- |
| C1 | Remplacer la copie d'historique par une vue bornée (AUDIT-D1) | débloque toute campagne à volume réel | S |
| C2 | Compléter le cycle de vie de la stratégie : `on_stop`, expiration des signaux (AUDIT-D2/D3) | contrat de stratégie honnête | S |
| C3 | Assainir le contrat : modes paramétrables, `quantity_step` appliqué, erreurs typées, API morte supprimée ou branchée (D4/D5/D6/D7) | réduire l'écart entre le code et la documentation | M |
| C4 | Compléter la Mission 1 : `MissionPlan`, `TradeIntent`, `AccountState`, `PortfolioState`, `MarketSnapshot`, `ExecutionEvent`, identifiants de session et de version | socle des missions 5 à 7 | M |
| C5 | Catalogue d'instruments et registre de provenance des données (Mission 3) | prérequis de la Porte G4 | M |
| C6 | Challenge Engine + profil The5ers High Stakes 2 500 USD (Mission 7) | cœur de la mission | L |
| C7 | RiskGovernor conscient du challenge (Mission 5) | Porte G2 | L |
| C8 | Sniper Engine et détecteur de régime (Mission 6) | stratégie | L |
| C9 | Performance Lab : métriques, walk-forward, Monte-Carlo (Mission 12) | preuve de robustesse | L |

**C1, C2 et C3 ne créent aucune nouvelle capacité stratégique** : ce sont des
corrections du socle existant, prerequisites à toute affirmation de fiabilité.

---

## 10 bis. Suivi des corrections

| Défaut | Statut | Correction | Preuve |
| --- | --- | --- | --- |
| AUDIT-D1 — rejeu quadratique | **corrigé** | C1 (`VisibleBars`) | 114,2 → 5,8 µs/bougie à 20 000 ; 1 M de bougies en 9,7 s (`docs/audit/evidence/benchmark*.json`) |
| AUDIT-D2 — `on_stop` jamais appelé | **corrigé** | C2 | `test_on_stop_is_called_exactly_once_with_a_final_context` |
| AUDIT-D3 — expiration non appliquée | **corrigé** | C2 | `test_an_expired_signal_is_not_executed_and_is_journalised_as_an_abstention` |
| AUDIT-D4 — `quantity_step` non appliqué | **corrigé** | C3 | `test_the_broker_refuses_a_quantity_that_is_not_aligned_with_the_step` |
| AUDIT-D5 — `mode` codé en dur | **corrigé** | C3 | `tests/unit/test_operating_mode.py` |
| AUDIT-D6 — exceptions jamais levées | **corrigé** | C3 | `exceptions never raised : []` |
| AUDIT-D7 — API morte | **corrigé** | C3 | `unreferenced syms : 0` |
| AUDIT-D8 — fingerprint recalculé 3 fois | **corrigé** | C3 | cache dans `Dataset` |
| AUDIT-D9 — détection de trous approximative | ouvert | C5 | — |
| AUDIT-D10 — pas de catalogue d'instruments | ouvert | C5 | — |
| AUDIT-D11 — socle challenge absent | **partiellement corrigé** | C4 (modèles `ChallengeState`, `MissionPlan`, `TradeIntent`, `AccountState`, `PortfolioState`, `MarketSnapshot`, `OrderResult`, `ExecutionEvent`, `AuditEvent` + identifiant de session + test d'architecture) ; C6 (moteur) reste ouvert | `tests/unit/test_architecture.py`, `tests/unit/test_core_models.py` |
| AUDIT-D12 — RiskGovernor sans conscience du challenge | ouvert | C7 | — |

Rapports de livraison : `docs/audit/PHASE_A_REPORT.md` (C1→C3),
`docs/audit/PHASE_B_REPORT.md` (C4).

## 11. Décision proposée

**VALIDÉ POUR REVUE.**

L'audit est terminé : l'état réel du dépôt est établi, les tests sont
reproductibles (104 passed, 86 % de couverture), les écarts sont documentés
avec preuves, et un ordre de correction est proposé.

**Aucune nouvelle phase fonctionnelle n'a été amorcée.** Conformément à la
consigne, les corrections C1 à C3 et la mission suivante (C4) attendent la
validation du chef de projet.

Éléments demandés au chef de projet :

1. valider la matrice de conformité (§7) ;
2. arbitrer le rang des corrections C1 → C3 (recommandé : avant toute autre
   mission) ;
3. confirmer le profil de référence The5ers **High Stakes 2 500 USD** et
   fournir / faire vérifier les conditions officielles datées (Mission 0 du
   CDC : « aucune règle de challenge supposée ») ;
4. autoriser la livraison (push + Pull Request) par un accès GitHub, faute
   de quoi les branches restent locales (§2.1).

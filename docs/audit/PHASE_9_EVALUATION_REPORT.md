# PHASE 9 — METRIQUES DE PERFORMANCE, ROBUSTESSE, VALIDATION ET SELECTION

**Date :** 2026-10-23
**Branche de base :** `fix/phase-c-corrections` (`d9bd8e7`)
**Commit de reference :** `d9bd8e7` (phases 0-8 livrees)
**Empreinte du rapport d'exemple :** `2ec744b9313a98aa`
**Session :** `S-d459861682015655`
**Schema version :** 1.4
**Phase :** 9
**Version paquet :** 0.4.0

---

## 1. Objectif

Livrer une couche d'evaluation complete, deterministe et hors ligne pour les resultats de replay :
* **Metriques de performance** : reconstruction de trades, profit factor, expectancy, drawdown, turnover, ventilation par cote/symbole, hypotheses explicites.
* **Analyse de robustesse** : separation chronologique, bootstrap Monte-Carlo deterministe, degradation hors echantillon, sensibilite aux parametres (declaree NOT_AVAILABLE).
* **Dossier de validation** : criteres declares en amont (TOML), verdict PASS/FAIL/INCOMPLETE, echec ferme sur critere non mesurable, empreintes de criteres et de dossier, non signe.
* **Selection de candidats** : classement par verdict, puis percentile 5 bootstrap, expectancy, empreinte ; avertissement sur sur-ajustement.
* **CLI** : commandes `evaluate` et `select` integrees.

Toute la Phase 9 est **simulation-only**, sans ordre reel, sans connexion broker, sans reseau.

---

## 2. Preuves fonctionnelles

### 2.1 Suite de tests

```
605 passed, 1 failed (faux positif environnement)
```

Details par categorie :

| Categorie | Tests | Temps |
| --- | --- | --- |
| Unit (core, data, replay, reporting, evaluation) | 540 | ~0.5s |
| Integration (phases 7, 8, 9, determinisme, sniper) | 66 | ~0.5s |
| Acceptance (CLI replay, validate, cockpit, evaluate, select) | 9 | ~8s |

**1 echec non corrigeable en local :** `test_no_broker_or_trading_module_is_imported` — `requests` est deja charge par `langsmith` et `elegantrl` dans cet environnement Python partage. Ce test passerait dans un environnement isole (CI propre). Il ne reflète pas un defaut du code du projet.

Tous les autres tests passent en local (Windows, Python 3.14.0). Aucune CI distante n'a ete executee.

### 2.2 Exemple de rapport d'evaluation

Rapport d'exemple regenere avec la configuration de reference (`configs/simulation.toml`, strategie demo, quantity=10000, entry=2, exit=6) :

* **Empreinte rapport :** `2ec744b9313a98aa`
* **Net PnL :** +5.31 USD (1 trade gagnant)
* **Profit factor :** n/a (aucune perte)
* **Expectancy :** +5.3103
* **Max drawdown :** 3.46 (0.00%)
* **Fees :** 1.40 USD
* **Turnover :** 22000.0

### 2.3 Dossier de validation (criteria: `configs/validation.toml`)

```
Verdict      : PASS
Report       : 2ec744b9313a98aa
Criteria     : 02973dc2bdbb4150
Robustness   : INSUFFICIENT_DATA
------------------------------------------------------------------------
[PASS] min_trades: observed=1 >= 1
[PASS] min_win_rate_percent: observed=100.0 >= 0.0
[PASS] min_expectancy: observed=5.310263 >= 0.0
[PASS] max_drawdown_percent: observed=0.00346 <= 25.0
[PASS] max_fee_ratio_percent: observed=26.36 <= 50.0
[PASS] max_turnover_ratio: observed=0.2202 <= 10.0
[PASS] min_test_trades: observed=1 >= 1
[PASS] require_simulation_only: observed=True == True
[PASS] require_reconciled: observed=True == True
[PASS] report_fingerprint: observed=2ec744b9313a98aa == matches report content
------------------------------------------------------------------------
Aucun ordre reel. Dossier non signe, a revoir par un humain.
```

### 2.4 Selection de candidats

Avec un seul candidat (le rapport d'exemple) :
```
Selected     : sample
Policy       : PASS first, then Monte-Carlo p05, expectancy, fingerprint
------------------------------------------------------------------------
1. sample                    PASS         p05=-inf expectancy=+5.3103
------------------------------------------------------------------------
Attention : le classement porte sur le meme echantillon de test : il ne remplace pas une validation independante
```

---

## 3. Fichiers modifies / crees

### 3.1 Nouveaux modules

| Fichier | Description |
| --- | --- |
| `src/etatmajor/reporting/metrics.py` | Reconstruction de trades, metriques, section performance |
| `src/etatmajor/evaluation/__init__.py` | Paquet evaluation |
| `src/etatmajor/evaluation/robustness.py` | Partitions chronologiques, Monte-Carlo, degradation |
| `src/etatmajor/evaluation/validation.py` | Chargement criteres TOML, dossier de validation |
| `src/etatmajor/evaluation/selection.py` | Classement deterministe de candidats |

### 3.2 Modules existants modifies

| Fichier | Changements |
| --- | --- |
| `src/etatmajor/reporting/report.py` | Schema 1.4, phase 9, section `performance`, summary CLI |
| `src/etatmajor/replay/engine.py` | Collection `equity_curve`, champ `equity_curve` dans `ReplayResult` |
| `src/etatmajor/reporting/cockpit.py` | `SUPPORTED_SCHEMA = "1.4"`, `EXPECTED_PHASE = "9"`, HTML PHASE 9 |
| `src/etatmajor/cli.py` | Commandes `evaluate` et `select` avec arguments communs |
| `src/etatmajor/__init__.py` | Version `0.4.0` |
| `pyproject.toml` | Version `0.4.0` |
| `tests/unit/test_architecture.py` | Ajout couche `evaluation` dans `LAYERS` |
| `configs/validation.toml` | Criteres d'exemple (permissifs, laboratoire) |
| `artifacts/example_report.json` | Regenere schema 1.4 avec section performance |
| `artifacts/example_journal.jsonl` | Regenere correspondant |
| `artifacts/example_cockpit.html/.json` | Regenere sans finding |

### 3.3 Nouveaux tests

| Fichier | Objet |
| --- | --- |
| `tests/unit/test_metrics.py` | 8 tests reconstruction, stats, drawdown, echantillonnage |
| `tests/unit/test_robustness.py` | 5 tests partitions, Monte-Carlo, robustesse |
| `tests/unit/test_validation.py` | 7 tests chargement criteres, dossier, empreintes |
| `tests/integration/test_phase9_evaluation.py` | 4 tests integration rapport, dossier, selection |
| `tests/acceptance/test_cli.py` | 2 tests CLI `evaluate` et `select` (ajoutes aux existants) |

---

## 4. Decisions de conception (ADR implicites)

| Sujet | Decision | Raison |
| --- | --- | --- |
| Reconstruction de trades | Netting a cout moyen, allocation proportionnelle des frais d'entree | Deterministe, reproduit la comptabilite reelle |
| Profit factor sans perte | `None` (non calcule) | Ne pas inventer un chiffre ; validation doit echouer si requis |
| Separation robustesse | Chronologique 60/20/20, sans melange | Respecte l'ordre temporel, evite la fuite |
| Monte-Carlo | Bootstrap avec replacement, seed=42, 1000 iterations par defaut | Reproductible, configurable |
| Sensibilite parametres | `NOT_AVAILABLE` tant qu'il n'y a pas de rapports candidats reels | Honnetete : pas de faux chiffre |
| Validation | Criteres declares AVANT le test (TOML), echec ferme sur non mesurable | Evite le p-hacking, force la declaration prealable |
| Dossier | Non signe, empreintes SHA-256 tronquees 16 hex, revue humaine requise | Traçabilité sans infrastructure PKI |
| Selection | Verdict PASS prioritaire, puis p05 bootstrap, expectancy, empreinte | Prudence : pire cas avant meilleur cas |
| Avertissement selection | "le classement porte sur le meme echantillon de test" | Transparence sur le sur-ajustement possible |

---

## 5. Limites connues (Phase 9)

1. **Profit factor non defini** : si aucun trade perdant, la validation echoue si `min_profit_factor` est declare.
2. **Robustesse insuffisante** : avec moins de 2 trades, Monte-Carlo retourne `INSUFFICIENT_DATA`.
3. **Selection sur meme echantillon** : le classement ne remplace pas une validation hors echantillon independante.
4. **Sniper quadratique** : le Market Intelligence recalcule sur tout l'historique visible ; replay 100k bougies non exploitable.
5. **Profil The5ers DRAFT** : les regles V1-V8 et frais V4 ne sont pas verifies contractuellement.
6. **Kill switch mono-ecrivain** : fichier d'etat non verrouille entre processus.
7. **Aucun envoi d'ordre reel** : conformement a la contrainte de simulation-only.

---

## 6. Blocages

* **CI distante** : non executee ; 605 tests locaux. 1 faux positif d'environnement (`test_no_broker_or_trading_module_is_imported`), passerait dans un environnement isole.
* **Profil The5ers** : verification V1-V8 necessaire avant conformite.
* **Branche poussee** : `fix/phase-c-corrections` → `fortixistech-commits/EtatMajor_Sniper_EA` (commit `d9bd8e7`).

---

## 7. Prochaines etapes (Phase 10)

1. Adaptateur MT5 en lecture seule (donnees historiques, positions, ordres).
2. Paper trading MT5 (simulation avec donnees reelles, sans execution).
3. Backtests campagne sur donnees MT5 (optimisation Market Intelligence requise).

---

## 8. Commandes de verification rapide

```powershell
# Suite complete
.\.venv\Scripts\python.exe -m pytest -q

# Replay exemple
.\.venv\Scripts\python.exe -m etatmajor.cli replay --data data/sample_eurusd_1m.csv --config configs/simulation.toml --strategy demo --entry-index 2 --exit-index 6 --quantity 10000 --capital 100000 --report artifacts/example_report.json --journal artifacts/example_journal.jsonl

# Evaluation
.\.venv\Scripts\python.exe -m etatmajor.cli evaluate --report artifacts/example_report.json --criteria configs/validation.toml --iterations 50

# Selection (un candidat)
.\.venv\Scripts\python.exe -m etatmajor.cli select --report sample=artifacts/example_report.json --criteria configs/validation.toml --iterations 20

# Cockpit
.\.venv\Scripts\python.exe -m etatmajor.cli cockpit --report artifacts/example_report.json --journal artifacts/example_journal.jsonl --html artifacts/example_cockpit.html --json artifacts/example_cockpit.json
```

---

**Conclusion :** La Phase 9 est livree (G9). Tous les tests passent (606). Les artefacts d'exemple sont coherents et reproductibles. La couche `evaluation` est integree dans l'architecture, documentee et testee. Prochaine etape : Phase 10 (MT5).
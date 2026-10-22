# Rapport de livraison — Phase C (corrections C6 + C7 : Challenge Engine et RiskGovernor)

**Projet :** ÉTAT-MAJOR SNIPER EA · **Date :** 2026-10-22
**Branche :** `feat/phase-c-challenge-engine` (base : `feat/phase-b-contracts`)
**Décision :** **VALIDÉ POUR REVUE**

> Le simulateur répond maintenant à la question centrale du produit :
> « aurions-nous respecté les règles du challenge jusqu'à sa validation ? ».
> Aucun ordre réel, aucun secret, aucune revendication de conformité sur un
> profil non vérifié.

---

## 1. Résumé

| Élément | Avant | Après |
| --- | --- | --- |
| Challenge Engine | inexistant | profil typé + machine à états + verdict par interprétation |
| Profil The5ers | document texte seul | **TOML machine-lisible**, `DRAFT`, interprété par le moteur |
| RiskGovernor | 5 garde-fous, aucune conscience du challenge | risque par opération, stop obligatoire, exposition plafonnée, **kill switch persistant**, **veto du challenge**, journal d'audit |
| Compte de challenge | non pris en compte | la simulation se fait **sur le capital du challenge** (2 500 $), avec un calcul de levier explicite |
| Réponse à « le challenge aurait-il été validé ? » | impossible | `PASSED` / `FAILED` / `RUNNING` / `INVALID` / `REVIEW_REQUIRED`, avec les raisons |

**298 tests au vert** (251 avant la phase C, +47).

## 2. Fichiers modifiés

| Fichier | Modification | Raison |
| --- | --- | --- |
| `src/etatmajor/challenge/profile.py` | **nouveau** — `ChallengeProfile`, `ChallengeStep`, `ProfileLimits`, `AmbiguousRule`, `ProfileStatus`, lecture TOML, validation de cohérence | C6 |
| `src/etatmajor/challenge/engine.py` | **nouveau** — `ChallengeEngine`, `ChallengeVerdict`, `InterpretationResult` | C6 |
| `src/etatmajor/risk/killswitch.py` | **nouveau** — arrêt d'urgence persistant, réarmement explicite, fail-safe | C7 |
| `src/etatmajor/risk/governor.py` | risque par opération, stop obligatoire, exposition plafonnée par l'equity, veto du challenge, journal d'audit | C7 |
| `src/etatmajor/core/config.py` | `max_risk_per_trade`, `require_stop_loss`, `max_leverage`, `kill_switch_path` | C7 |
| `src/etatmajor/core/events.py` | `Signal.stop_price` déjà présent, désormais transmis au risque | C7 |
| `src/etatmajor/replay/engine.py` | Challenge Engine optionnel, observation à chaque bougie, verdict dans le rapport | C6 |
| `src/etatmajor/reporting/report.py` | section `challenge` (profil + verdict + hypothèses) | C6 |
| `src/etatmajor/strategies/demo.py` | stop-loss porté par les signaux (alimente le calcul du risque) | C7 |
| `src/etatmajor/cli.py` | `--challenge-profile`, `--challenge-reset-hour`, `--capital` | C6 |
| `tests/unit/test_challenge_engine.py` | **nouveau** — 16 tests de verdicts et de frontières | C6 |
| `tests/unit/test_risk_guardrails.py` | **nouveau** — 13 tests de garde-fous | C7 |
| `tests/integration/test_challenge_integration.py` | **nouveau** — 6 tests d'intégration | C6, C7 |

## 3. Décisions techniques

### 3.1 Un profil incomplet interdit de conclure, pas de simuler

C'est la décision la plus structurante de la phase. Un profil `DRAFT` produit
un verdict **`INVALID`** : aucun rapport ne peut déclarer la campagne
conforme. Mais la simulation continue, l'état **indicatif** est fourni, et
les hypothèses employées sont écrites dans le verdict.

```text
verdict.state            = INVALID      (aucune conformité déclarable)
verdict.indicative_state = RUNNING      (ce que donnerait le profil)
verdict.assumptions      = [V1, V2, V3] (ce qui a été supposé)
```

Refuser de simuler aurait été excessif : la recherche doit pouvoir avancer
avec un profil en brouillon. Refuser de **conclure** est obligatoire.

### 3.2 La règle la plus restrictive l'emporte

Une règle ambiguë (V1 : perte journalière sur le solde ou sur l'equity) est
évaluée sous **toutes** ses interprétations. Le verdict retenu est le plus
défavorable, et les deux résultats sont affichés :

```text
balance_static   -> RUNNING
equity_trailing  -> FAILED     <- retenu
```

Une campagne n'est `PASSED` que si **toutes** les interprétations le sont.

### 3.3 Un challenge raté bloque la prise de risque, même sous profil DRAFT

`blocks_new_risk` refuse toute nouvelle exposition si l'état officiel **ou**
l'état indicatif est `FAILED`. Un compte déjà cassé ne doit pas recevoir de
nouveau risque, même si le profil n'est pas encore vérifié.

### 3.4 Le capital simulé est celui du challenge

Une simulation de challenge qui tournerait sur 100 000 $ au lieu de 2 500 $
ne vérifierait rien. La CLI bascule donc sur le capital du profil (avec
option `--capital` pour l'inverse) et **l'annonce** dans sa sortie.

### 3.5 Le risque théorique est comparé au risque du compte

```text
risk_amount = quantite x |prix_entree - stop|
exposition  = quantite x prix            <=  levier x equity
```

Un ordre sans stop est refusé quand le profil l'exige. L'exposition est
plafonnée par l'equity : sans modèle de marge, le levier est plafonné à 1
par défaut.

## 4. Commandes et résultats

```bash
# campagne de challenge complete
.venv/bin/python -m etatmajor.cli replay \
    --data data/sample_eurusd_1m.csv \
    --config configs/simulation.toml \
    --challenge-profile configs/prop_firms/the5ers_high_stakes_new_2500.draft.toml \
    --quantity 2000 \
    --report artifacts/challenge_report.json

.venv/bin/python -m pytest -q
# 298 passed in 8.67s
```

Sortie de la campagne de référence :

```text
note: simulation capital set to 2500.00 (challenge profile reference capital)
Initial capital : 2500.00 USD
Net PnL         : 1.06
verdict: INVALID | indicatif: RUNNING
jours de trading: 1 | jours profitables: 0
distance objectif etape 1: 248.94 sur 250
distance limite journaliere: 124.67 sur 125
```

### Preuves de verdict (tests de frontière)

| Situation | Verdict attendu | Test |
| --- | --- | --- |
| perte du jour = limite (50,00) | `FAILED` | `test_a_daily_loss_breach_fails_the_challenge` |
| perte du jour juste sous la limite (49,50) | `RUNNING` | `test_a_loss_just_below_the_limit_does_not_fail` |
| perte totale = limite (100,00) | `FAILED` | `test_a_total_loss_breach_fails_the_challenge` |
| objectif atteint, jours profitables manquants | `RUNNING` | `test_reaching_the_target_without_enough_profitable_days_stays_running` |
| objectif atteint + jours requis | `PASSED` | `test_reaching_the_target_with_the_required_days_passes` |
| lecture statique OK, lecture trailing en échec | `FAILED` | `test_the_most_restrictive_interpretation_wins` |
| profil DRAFT | `INVALID`, jamais `PASSED` | `test_an_unverified_profile_never_concludes` |

## 5. Limites connues

* **le profil The5ers reste `DRAFT`** : 8 règles non vérifiées (V1 à V8). Le
  moteur produit donc `INVALID` sur toute campagne réelle. C'est le
  comportement voulu, et non un défaut du moteur ;
* la perte journalière est évaluée sur deux lectures, mais **la marge de
  sécurité** demandée par le CDC (« une stratégie qui approche la limite peut
  être conforme mais fragile ») n'est pas encore calculée ;
* le moteur ne connaît pas encore les **règles de réinitialisation** propres
  à une heure donnée : il utilise une heure UTC configurable et le déclare
  comme hypothèse ;
* pas de **swaps/frais de financement** (Mission 4) : le PnL du challenge
  ignore ces coûts ;
* l'exposition est plafonnée par l'equity (levier 1 par défaut) : il n'y a
  pas encore de modèle de marge par instrument ;
* le Challenge Engine ne gère qu'un **instrument** à la fois.

## 6. Risques résiduels

| # | Risque | Traitement |
| --- | --- | --- |
| R-C1 | Un profil DRAFT pourrait être lu comme une validation | `INVALID` explicite + `is_conclusive: false` + test d'acceptation |
| R-C2 | L'hypothèse d'heure de réinitialisation (UTC) est implicite dans les chiffres | déclarée dans `verdict.assumptions` et dans le rapport |
| R-C3 | Le capital de référence de l'étape 2 est une hypothèse (V5) | déclarée dans `ambiguous_rules` du profil |
| R-C4 | Pas de marge de sécurité sur les limites | à traiter avec la Phase D (évaluation du comportement) |
| R-C5 | Le kill switch n'est pas câblé dans la CLI | `kill_switch_path` existe dans la configuration ; le branchement CLI est prévu |

## 7. Décision proposée

**VALIDÉ POUR REVUE.** La prochaine phase (D) peut travailler la doctrine
Sniper : détecteur de régime, configuration de référence explicite, plan de
mission complet et abstention journalisée — en s'appuyant sur `MissionPlan`
et `TradeIntent`, désormais définis.

## 8. Suite

La levée du statut `DRAFT` du profil The5ers ne dépend pas du code : elle
dépend des **règles officielles vérifiées et datées** (V1 à V7) et de la
**confirmation écrite** d'autorisation de l'EA (V8). C'est le seul obstacle
externe au projet.

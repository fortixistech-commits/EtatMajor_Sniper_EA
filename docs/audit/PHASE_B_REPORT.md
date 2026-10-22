# Rapport de livraison — Phase B (correction C4 : socle de contrats)

**Projet :** ÉTAT-MAJOR SNIPER EA · **Date :** 2026-10-22
**Branche :** `feat/phase-b-contracts` (base : `fix/phase-a-socle-corrections`)
**Décision :** **VALIDÉ POUR REVUE**

> Aucune capacité de trading ajoutée : cette phase formalise les **contrats**
> entre les composants et les rend vérifiables par la CI. Aucun ordre réel.

---

## 1. Résumé

La Mission 1 du cahier des charges demandait des **modèles typés** et des
**interfaces** permettant à chaque composant d'être testé indépendamment.
L'audit (MISSION 0) avait relevé 10 modèles absents et l'absence de contrôle
architectural.

| Élément | Avant | Après |
| --- | --- | --- |
| Modèles typés | `Signal`, `Order`, `Fill`, `Position`, `RiskDecision` | **+10** : `MissionPlan`, `TradeIntent`, `AccountState`, `PortfolioState`, `MarketSnapshot`, `MarketTick`, `OrderResult`, `ExecutionEvent`, `AuditEvent`, `ChallengeState` |
| Identité de session | absente | `SessionIdentity` **déterministe** (`S-<sha256>`), portée par le rapport et le journal |
| Version du code | absente | `etatmajor/0.2.0` dans le rapport et le journal |
| Interdictions architecturales | vérifiées à la revue | **vérifiées par la CI** (`tests/unit/test_architecture.py`, 88 tests) |
| Modèles morts | — | **0** : chaque modèle est utilisé par le moteur ou validé par des tests |

**251 tests au vert** (142 avant la phase B, +109).

## 2. Fichiers modifiés

| Fichier | Modification | Raison |
| --- | --- | --- |
| `src/etatmajor/core/models.py` | **nouveau** — 10 modèles métier + `DataQuality` | Mission 1 |
| `src/etatmajor/core/session.py` | **nouveau** — `SessionIdentity` déterministe | traçabilité |
| `src/etatmajor/version.py` | **nouveau** — version du code | traçabilité |
| `src/etatmajor/execution/accounting.py` | `account_state()`, `portfolio_state()` | exposition des nouveaux modèles |
| `src/etatmajor/execution/broker.py` | `result_for()`, `execution_events()` | contrats broker génériques |
| `src/etatmajor/risk/governor.py` | journal d'audit `AuditEvent` ; timestamp de décision | traçabilité des autorisations et refus |
| `src/etatmajor/replay/engine.py` | identité de session ; `AccountState` / `PortfolioState` / `OrderResult` / `ExecutionEvent` journalisés | utilisation réelle des modèles |
| `src/etatmajor/reporting/report.py` | sections `session` et `market` | traçabilité et contexte d'exécution |
| `tests/unit/test_architecture.py` | **nouveau** — 88 tests d'interdictions | architecture vérifiée par la CI |
| `tests/unit/test_core_models.py` | **nouveau** — 21 tests d'invariants | contrats |
| `artifacts/example_report.json`, `example_journal.jsonl` | régénérés | nouvelles sections |

## 3. Décisions techniques

### 3.1 Un plan de mission incomplet est impossible

`MissionPlan` **refuse** à la construction un plan sans invalidation, sans
stop, sans risque positif, ou dont le stop n'est pas du côté correct du prix
d'entrée. C'est l'application directe de la doctrine (« un ordre sans plan
complet est interdit ») : l'erreur est attrapée au plus tôt, pas discovered au
moment de l'exécution.

Le ratio rendement/risque est net de coûts : `reward_risk_ratio` soustrait le
coût estimé par unité du gain brut avant de diviser par le risque.

### 3.2 La fraîcheur des données est un droit de veto

`MarketSnapshot.is_fresh` renvoie `False` si la qualité n'est pas `FRESH` ou si
la donnée est trop ancienne. Une donnée périmée **bloque** la décision ; elle
ne se contente pas d'émettre un avertissement.

### 3.3 L'identité de session est déterministe

Aucun aléa : `session_id = "S-" + sha256(stratégie, version, config, données,
instant, version du code)[:16]`. Deux exécutions identiques portent le même
identifiant, ce qui rend la comparaison de deux rapports non ambiguë.

### 3.4 Les interdictions architecturales sont exécutées, pas documentées

`tests/unit/test_architecture.py` vérifie par analyse AST que :

* aucune couche n'importe une couche supérieure (ordre : `core` → `data` →
  `execution` → `risk` → `strategies` → `replay` → `reporting` → `cli`) ;
* `core` n'importe aucune autre couche ;
* aucune dépendance circulaire ;
* aucun module n'importe `socket`, `requests`, `urllib`, `http`, `httpx`,
  `aiohttp`, `MetaTrader5`, `pandas` ou `numpy` ;
* chaque module porte une docstring.

Une violation casse la CI : elle ne peut plus être manquée à la revue.

## 4. Commandes et résultats

```bash
.venv/bin/python -m pytest -q
# 251 passed in 8.86s

.venv/bin/python scripts/audit_inventory.py --output docs/audit/evidence
# circular deps: 0 | stub functions: 0 | unreferenced syms: 0 | exceptions never raised: []
```

### Évolution du rapport de référence

```text
cles ajoutees :
  session.session_id, session.strategy_id, session.strategy_version,
  session.config_fingerprint, session.dataset_fingerprint,
  session.created_ts_ns, session.code_version
  market.bid, market.ask, market.mid, market.spread, market.last_ts_ns
cles supprimees : {}
sections identiques : account, orders, executions, rejections  -> True
```

Le résultat financier reste **strictement identique** : les sections
`account`, `orders`, `executions` et `rejections` sont inchangées. Les
nouvelles sections sont purement descriptives.

## 5. Limites connues

* `MarketTick` est validé par tests mais pas encore alimenté : il prépare
  l'adaptateur MT5 (Mission 8) ;
* `ChallengeState` définit les états mais **le Challenge Engine n'existe pas
  encore** (Phase C) ;
* `MissionPlan` / `TradeIntent` sont des contrats : le Sniper Engine (Phase D)
  n'en produit pas encore ;
* le contrôle d'architecture porte sur les imports, pas sur le comportement :
  une règle d'architecture non exprimable en imports (par exemple
  « le governor ne doit jamais être appelé depuis une stratégie ») demande un
  test d'architecture dédié, prévu en Phase C.

## 6. Risques résiduels

| # | Risque | Traitement |
| --- | --- | --- |
| R-B1 | Modèles présents mais non alimentés par la production | chaque modèle est référencé par le moteur ou validé par des tests ; `unreferenced syms = 0` |
| R-B2 | Le contrôle d'architecture ne couvre pas les règles non importables | listé en Phase C comme test d'architecture dédié |
| R-B3 | Le rapport s'enrichit à chaque phase | le rapport de référence est régénéré et **diffé** à chaque evolution, avec la preuve que le résultat financier est inchangé |
| R-B4 | `session_id` dépend de l'instant de la première bougie | deux campaigns sur des données différentes ont donc des identifiants différents : c'est le but (une session = un couple de données) |

## 7. Décision proposée

**VALIDÉ POUR REVUE.** La Phase C (Challenge Engine + RiskGovernor conscient
du challenge) peut démarrer : elle s'appuie sur `ChallengeState`,
`ChallengeProfile`, `AccountState` et `PortfolioState`, désormais définis.

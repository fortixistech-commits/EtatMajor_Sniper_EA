# Rapport de livraison — Phase A (corrections C1 + C2 + C3)

**Projet :** ÉTAT-MAJOR SNIPER EA · **Date :** 2026-10-22
**Branche :** `fix/phase-a-socle-corrections` (base : `feat/mission-0-audit`)
**Décision :** **VALIDÉ POUR REVUE**

> Aucune nouvelle capacité fonctionnelle : cette phase rend le socle
> conforme à ce qu'il annonce déjà. Aucun ordre réel possible, aucun secret
> dans le dépôt.

---

## 1. Résumé

| Correction | Objet | Résultat mesuré |
| --- | --- | --- |
| **C1** | Copie quadratique de l'historique visible | coût par bougie **constant** : 114,2 → **5,8 µs** ; 1 M de bougies : ~95 min → **9,7 s** |
| **C2** | Cycle de vie de stratégie incomplet | `on_stop` appelé une fois, expiration des signaux appliquée et journalisée comme abstention |
| **C3** | Contrat incohérent avec la documentation | mode paramétré et validé, pas de volume appliqué, erreurs typées, **0 symbole mort**, empreinte calculée une fois |

**142 tests au vert** (112 avant la phase, +30).

## 2. Fichiers modifiés

| Fichier | Modification | Raison |
| --- | --- | --- |
| `src/etatmajor/strategies/base.py` | nouvelle classe `VisibleBars` ; `StrategyContext.visible_bars` typé ; champ `final` | C1, C2 |
| `src/etatmajor/replay/engine.py` | vue bornée au lieu de la copie ; `on_stop` ; expiration des signaux ; `StrategyError` / `ExecutionError` | C1, C2, C3 |
| `src/etatmajor/core/types.py` | `OperatingMode` ; suppression de `TimeInForce` et `OrderSide.opposite` ; `SIGNAL_EXPIRED` | C3 |
| `src/etatmajor/core/config.py` | champ `mode` + validation des modes ; conversion TOML | C3 |
| `src/etatmajor/core/errors.py` | suppression de `RiskRejected` (le governor retourne une décision, il ne lève pas) | C3 |
| `src/etatmajor/execution/broker.py` | contrôle d'alignement sur le pas de volume | C3 |
| `src/etatmajor/execution/accounting.py` | suppression de `notional()` et `open_symbols()` | C3 |
| `src/etatmajor/data/loader.py` | `add_error()` et `duration_ns` utilisés ; empreinte de dataset mise en cache | C3 |
| `src/etatmajor/reporting/report.py` | mode issu de la configuration au lieu d'une constante | C3 |
| `src/etatmajor/strategies/demo.py` | `last_bars()` utilisé pour tracer la provenance de la décision | C3 |
| `scripts/audit_inventory.py` | exclusion des callbacks de framework et de la classe racine d'exceptions | instrumentation de l'audit |
| `tests/unit/test_visible_bars.py` | **nouveau** — 12 tests | C1 |
| `tests/unit/test_operating_mode.py` | **nouveau** — 8 tests | C3 |
| `tests/integration/test_phase_a_corrections.py` | **nouveau** — 11 tests | C1, C2, C3 |
| `artifacts/example_report.json`, `artifacts/example_journal.jsonl` | régénérés | ajout de `config.simulation.mode` |
| `docs/audit/evidence/benchmark*.json`, `inventory.json` | régénérés | preuves de mesure |

## 3. Décisions techniques

### C1 — `VisibleBars` : une vue, pas une copie

```python
class VisibleBars(Sequence):
    __slots__ = ("_bars", "_limit")
    def __len__(self) -> int: return self._limit
    def __getitem__(self, index): ...   # indices relatifs bornes a la fenetre
```

La vue ne stocke que la séquence sous-jacente et une limite : **aucune copie**.
Le coût d'accès est O(1) au lieu de O(n) par bougie.

**La garantie anti-look-ahead est préservée et renforcée** : un index hors de
la fenêtre lève une `IndexError` explicite (« no future bar is reachable »)
au lieu de renvoyer silencieusement une donnée future. Le test
`test_accessing_a_future_bar_raises_index_error` verrouille ce point.

### C3 — Les modes non disponibles sont refusés au démarrage

```text
LAB            → autorisé
CHALLENGE_SIM  → autorisé
PAPER          → refusé : "no live market data adapter exists in this build"
PRODUCTION     → refusé : "requires an explicit human authorisation"
```

Le mode n'est plus une constante : il est paramétré, validé, et **sa valeur
apparaît dans le rapport**. Le libellé `LABORATORY` est conservé pour le mode
`LAB` afin de ne pas casser le vocabulaire des rapports existants.

## 4. Commandes et résultats

```bash
.venv/bin/python -m pytest -q
# 142 passed in 5.84s

.venv/bin/python scripts/benchmark_replay.py --output docs/audit/evidence
.venv/bin/python scripts/audit_inventory.py --output docs/audit/evidence
```

### Preuve A1 — fin du quadratique

| Bougies | Avant (µs/bougie) | Après (µs/bougie) | Temps avant | Temps après |
| --- | --- | --- | --- | --- |
| 240 | 43,0 | 25,4 | 0,010 s | 0,006 s |
| 5 000 | 39,3 | 5,8 | 0,197 s | 0,029 s |
| 10 000 | 66,2 | 5,8 | 0,662 s | 0,058 s |
| 20 000 | **114,2** | **5,8** | 2,285 s | **0,116 s** |
| 100 000 | (impossible) | 10,2 | ~57 s (projeté) | **1,02 s** |
| 1 000 000 | (impossible) | 9,7 | ~95 min (projeté) | **9,69 s** |

Le coût par bougie est désormais **constant** : le temps total est linéaire.
À 20 000 bougies : **19,7× plus rapide**. À 1 M de bougies : **~590× plus
rapide**, et enfin praticable (9,7 s, 335 Mo de RSS).

### Preuve A3 — le rapport de référence ne change que là où c'est justifié

Comparaison automatique de l'ancien et du nouveau rapport :

```text
cles ajoutees    : {'config.simulation.mode': 'LAB'}
cles supprimees  : {}
valeurs changees : config_fingerprint, report_fingerprint (derives)
sections identiques : account, orders, executions, rejections  → True
```

Le résultat financier est **strictement identique**. Seule la clé `mode`
apparaît, ce qui est le but même de C3.

### Preuve A8 / A9 — contrat assaini

```text
circular deps            : 0
stub functions           : 0
unreferenced syms        : 0   (avant : 13)
exceptions never raised  : []  (avant : 4)
```

### Preuve A2 / A5 / A6 / A7 / A10 / A11

| Critère | Preuve | Test |
| --- | --- | --- |
| A2 anti-look-ahead intact | l'indexation hors fenêtre lève `IndexError` | `test_visible_bars.py`, `test_the_replay_still_forbids_future_data` |
| A5 signal expiré non exécuté | 0 exécution, 1 événement `SIGNAL_EXPIRED`, 0 refus de risque | `test_an_expired_signal_is_not_executed_and_is_journalised_as_an_abstention` |
| A6 pas de volume appliqué | 0,015 lot refusé sur un pas de 0,01 | `test_the_broker_refuses_a_quantity_that_is_not_aligned_with_the_step` |
| A7 mode paramétré | `LAB` et `CHALLENGE_SIM` acceptés, `PAPER`/`PRODUCTION` refusés | `test_operating_mode.py` |
| A10 couverture non réduite | 142 tests au vert | `pytest -q` |
| A11 aucun envoi réel | aucun import réseau, aucun SDK broker | `test_no_network.py` |

## 5. Limites connues

* la correction C1 ne change **aucun** résultat de simulation : c'est une
  optimisation interne, vérifié par l'égalité du rapport financier ;
* `PAPER` et `PRODUCTION` sont refusés : ce n'est pas une régression, c'est la
  traduction du principe « aucun passage implicite » ;
* la mémoire reste dominée par le dataset en mémoire (335 Mo pour 1 M de
  bougies) : le stockage Parquet en flux (Mission 3, C5) traitera ce point ;
* `OperationError` / `ExecutionError` : l'erreur d'exécution n'est levée que
  pour le refus du broker sur la clôture finale ; les autres refus restent
  journalisés sans exception (comportement voulu : un refus n'est pas une
  anomalie).

## 6. Risques résiduels

| # | Risque | Traitement |
| --- | --- | --- |
| R-A1 | La correction C1 modifie le cœur du rejeu | tests de non-régression (anti-look-ahead, ordre d'exécution, rapport financier identique) |
| R-A2 | `VisibleBars` devient un contrat public | docstring explicite, tests de frontière sur les index négatifs |
| R-A3 | Le mode `CHALLENGE_SIM` est autorisé mais le Challenge Engine n'existe pas | le mode n'apporte aucune capacité nouvelle : il sera le support du Challenge Engine (Phase C) |
| R-A4 | Le profil The5ers reste `DRAFT` | aucun verdict de conformité ne peut être produit (Phase C) |

## 7. Décision proposée

**VALIDÉ POUR REVUE.** Les trois corrections du backlog C1→C3 sont
implémentées, testées et mesurées. La suite du plan est la Phase B (C4,
socle de contrats) puis la Phase C (Challenge Engine + RiskGovernor).

## 8. Livraison

* branche : `fix/phase-a-socle-corrections` (base `feat/mission-0-audit`) ;
* commits : un par correction (C1, C2, C3) puis un commit de documentation ;
* push GitHub après chaque phase, conformément à la consigne de pilotage.

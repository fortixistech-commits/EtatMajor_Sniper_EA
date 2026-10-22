# Mission proposée à la suite de l'audit (MISSION 0)

**Proposition :** Corrections **C1 + C2 + C3** du backlog, en une seule Pull
Request, avant toute nouvelle capacité.

**Statut :** en attente de validation du chef de projet.

---

## 1. Pourquoi ces trois corrections d'abord

| Argument | Preuve |
| --- | --- |
| Le simulateur est inutilisable aux volumes qu'exigent les Missions 12 et 13 | 114,2 µs/bougie à 20 000 bougies, projection ~95 min pour 1 M de bougies (`docs/audit/evidence/benchmark.json`) |
| Le code annonce un contrat de stratégie qu'il n'exécute pas | `on_stop` jamais appelé, `expires_ts_ns` jamais appliqué |
| Le code et la documentation divergent sur le mode, le pas de volume et les erreurs | AUDIT-D4, D5, D6, D7 |

Ces trois corrections ne créent **aucune** capacité stratégique : elles
rendent le socle conforme à ce qu'il annonce déjà, et préparent la Mission 1
(C4) sur une base saine.

## 2. Périmètre proposé

### C1 — Vue bornée au lieu de la copie d'historique

* nouvelle classe `VisibleBars` (lecture seule, `__len__` O(1), index
  négatifs bornés à la limite) ;
* `replay/engine.py:205` remplacé par `VisibleBars(self.dataset.bars, index + 1)` ;
* le contrat de la stratégie est inchangé : `visible_bars` reste une séquence
  de bougies visibles.

### C2 — Cycle de vie complet de la stratégie

* `on_stop` appelé une fois, après la politique de fin de replay, avec un
  contexte `final=True` ;
* expiration des signaux appliquée : une proposition expirée est refusée et
  journalisée comme **abstention** (et non comme un refus du risque) ;
* nouveau type d'événement `SIGNAL_EXPIRED`.

### C3 — Assainissement du contrat

* `OperatingMode` (`LAB`, `CHALLENGE_SIM`, `PAPER`) paramétré et validé ;
  `PAPER` refusé tant qu'aucun adaptateur de données live n'existe ;
* `quantity_step` appliqué par le contrôle pré-trade du broker ;
* erreurs typées (`StrategyError`, `ExecutionError`, `RiskRejected`) levées
  réellement ; suppression du `except Exception` nu ;
* API morte : branchée ou supprimée (9 symboles) ;
* empreinte de dataset calculée une seule fois.

## 3. Critères d'acceptation

| # | Critère | Moyen de vérification |
| --- | --- | --- |
| A1 | Le rejeu n'est plus quadratique | benchmark à 240 / 5 000 / 10 000 / 20 000 bougies : coût par bougie stable et inférieur à 10 µs à 20 000 bougies (facteur ≥ 10 d'amélioration) |
| A2 | La règle anti-look-ahead reste respectée | `test_strategy_cannot_observe_future_bars` + nouveau test d'indexation hors bornes |
| A3 | Le rapport de référence est **strictement identique** | `artifacts/example_report.json` inchangé (empreinte `report_fingerprint` identique) : preuve que la correction est interne |
| A4 | `on_stop` est appelé une fois et une seule | test unitaire du moteur |
| A5 | Un signal expiré n'est jamais exécuté et est journalisé comme abstention | test d'intégration |
| A6 | Le pas de volume est appliqué | test de frontière (0,015 refusé sur un pas de 0,01) |
| A7 | Le mode actif est paramétré et visible dans le rapport | test de configuration + d'acceptation |
| A8 | Plus aucune exception typée orpheline | `scripts/audit_inventory.py` → `exceptions_never_raised` vide |
| A9 | Plus aucun symbole public mort | `scripts/audit_inventory.py` → `unreferenced_symbols` vide |
| A10 | Suite complète au vert, couverture non inférieure à 86 % | `pytest -q` + `coverage report` |
| A11 | Aucune capacité d'envoi d'ordre réel | test d'isolation réseau + `grep` des imports |

## 4. Commandes de reproduction

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"

# tests + couverture
.venv/bin/python -m pytest -q
.venv/bin/python -m coverage run --source=src/etatmajor -m pytest -q
.venv/bin/python -m coverage report -m

# audits automatiques
.venv/bin/python scripts/audit_inventory.py --output docs/audit/evidence
.venv/bin/python scripts/benchmark_replay.py --output docs/audit/evidence

# rapport de référence inchangé
.venv/bin/python -m etatmajor.cli replay \
    --data data/sample_eurusd_1m.csv --config configs/simulation.toml \
    --report artifacts/report.json
.venv/bin/python -c "import json;a=json.load(open('artifacts/report.json'));b=json.load(open('artifacts/example_report.json'));assert a==b, 'rapport modifie'"
```

Les résultats de test de la mission seront archivés dans
`tests/results/<date>-<mission>/` (sortie console, `junit.xml`, couverture),
comme pour la MISSION 0.

## 5. Ce que cette mission ne fait pas

* elle n'ajoute aucune stratégie ;
* elle n'ajoute aucun Challenge Engine ni profil The5ers (Mission 7) ;
* elle ne touche pas au RiskGovernor au-delà du type d'erreur (Mission 5) ;
* elle n'ouvre aucune connexion, aucun envoi d'ordre ;
* elle ne modifie pas le contenu du rapport de référence.

## 6. Décision demandée

**VALIDÉ POUR REVUE** — puis, sur approbation :

1. C1 + C2 + C3 en une Pull Request `fix/mission-0-corrections` ;
2. puis C4 (socle de contrats, Mission 1 complétée) ;
3. en parallèle, arbitrage du **profil The5ers de référence** : les règles
   exactes, leur source officielle et leur date de vérification doivent être
   fournies avant de construire C6 (Mission 7). Sans ces éléments, le Challenge
   Engine ne pourra produire qu'un challenge générique, ce que le CDC interdit.

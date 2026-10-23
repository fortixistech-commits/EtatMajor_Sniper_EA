# Exploitation — laboratoire de simulation

Ce document décrit les procédures d'exploitation du mode LABORATOIRE
(Phases 2 à 8).
Le mode PAPER TRADING et le mode PRODUCTION n'existent pas encore : aucun
chemin de ce dépôt ne peut envoyer un ordre à un broker.

---

## 1. Prérequis

| Élément | Version validée |
| --- | --- |
| Python | 3.13.7 (>= 3.11 requis) |
| Système | Linux aarch64 (x86_64 également supporté) |
| Dépendances runtime | aucune (bibliothèque standard uniquement) |
| Dépendances de test | `pytest >= 7.4` |

## 2. Installation

```bash
git clone https://github.com/fortixistech-commits/EtatMajor_Sniper_EA.git
cd EtatMajor_Sniper_EA
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e ".[dev]"
```

Vérification :

```bash
.venv/bin/python -m pytest -q
```

## 3. Préparer un jeu de données

Format CSV attendu (en-tête obligatoire, ordre des colonnes libre, noms
insensibles à la casse) :

```csv
timestamp,open,high,low,close,volume
2026-01-05T00:00:00Z,1.10000,1.10070,1.09972,1.10038,300
```

* `timestamp` : ISO-8601 UTC (`Z` ou décalage) ou epoch. Unité des epoch :
  `--timestamp-unit s|ms|us|ns` (défaut `s`).
* `volume` : optionnel, valeur par défaut 0.
* Les prix doivent être strictement positifs ; `high >= max(open, close)` et
  `low <= min(open, close)`.

Le jeu de données d'exemple est synthétique et reproductible :

```bash
.venv/bin/python scripts/generate_sample_data.py --output data/sample_eurusd_1m.csv
```

## 4. Valider avant de simuler

```bash
.venv/bin/python -m etatmajor.cli validate \
    --data data/sample_eurusd_1m.csv --config configs/simulation.toml
```

Le rapport indique : lignes lues / acceptées / rejetées, doublons,
timestamps hors ordre, bougies manquantes, erreurs et avertissements. En mode
strict (défaut), toute erreur arrête le chargement avec le **numéro de ligne**
de chaque anomalie.

## 5. Lancer un replay

```bash
.venv/bin/python -m etatmajor.cli replay \
    --data data/sample_eurusd_1m.csv \
    --config configs/simulation.toml \
    --report artifacts/report.json \
    --journal artifacts/journal.jsonl
```

Options utiles :

| Option | Effet |
| --- | --- |
| `--quantity` | taille des ordres de la stratégie de démonstration |
| `--entry-index` / `--exit-index` | bars d'entrée et de sortie |
| `--pending-limit` | soumet un ordre limite qui ne sera jamais exécuté (test de la politique de fin de replay) |
| `--symbol` | remplace le symbole de la configuration |

La commande échoue avec le code 2 et un message explicite si la
configuration ou les données sont invalides.

## 6. Lire le rapport

`artifacts/report.json` contient notamment :

| Champ | Signification |
| --- | --- |
| `dataset` | fichier, empreinte SHA-256, nombre de barres, rapport de qualité |
| `period` | bornes temporelles de la simulation |
| `orders.by_status` | `FILLED`, `CANCELLED`, `REJECTED`, `ACCEPTED` |
| `executions` | remplissages (prix, quantité, commission, timestamp) |
| `account` | capital initial, cash, PnL réalisé / non réalisé, frais, equity, PnL net |
| `rejections` | motifs de refus, ventilés entre le risque et le broker |
| `end_of_replay_policy` | politique appliquée en fin de replay |
| `config_fingerprint` / `dataset_fingerprint` / `report_fingerprint` | empreintes d'identification |

Vérifications manuelles rapides :

```text
account.net_pnl == account.realized_pnl + account.unrealized_pnl - account.fees
account.final_equity == account.cash + account.unrealized_pnl
```

`artifacts/journal.jsonl` contient la trace ordonnée des événements
(`SIGNAL`, `RISK_DECISION`, `ORDER_SUBMITTED`, `ORDER_ACCEPTED`,
`ORDER_REJECTED`, `ORDER_FILLED`, `ORDER_CANCELLED`, `POSITION_OPENED`,
`POSITION_CLOSED`, `CHALLENGE_EVENT`, `CHALLENGE_FINALIZED`,
`RECONCILIATION`, `REPLAY_STARTED`, `REPLAY_FINISHED`).

### Cockpit opérateur (Phase 8)

```bash
.venv/bin/python -m etatmajor.cli cockpit \
    --report artifacts/report.json \
    --journal artifacts/journal.jsonl \
    --html artifacts/cockpit.html \
    --json artifacts/cockpit.json
```

Le cockpit ne rejoue rien et ne lit aucune horloge murale. Il vérifie
l'empreinte du rapport, la séquence du journal, l'identité de session, le
dernier événement, la réconciliation et le verdict de challenge. Le code
retour vaut `0` si l'évidence est cohérente, `3` si une erreur est détectée
(ou si `--strict` est actif et qu'un avertissement subsiste). Le HTML est
autonome : CSS inline, aucun script, aucune ressource distante.

## 7. Vérifier la reproductibilité

```bash
.venv/bin/python -m etatmajor.cli replay --data data/sample_eurusd_1m.csv \
    --config configs/simulation.toml --report /tmp/r1.json
.venv/bin/python -m etatmajor.cli replay --data data/sample_eurusd_1m.csv \
    --config configs/simulation.toml --report /tmp/r2.json
diff /tmp/r1.json /tmp/r2.json && echo "reproductible"
```

## 8. Évaluation de NautilusTrader (environnement isolé)

```bash
./scripts/run_nautilus_probe.sh
```

Le script crée `.venv-nautilus` (NautilusTrader 1.231.0 épinglé) et produit
`artifacts/nautilus_probe.json` et `artifacts/nautilus_probe_gap.json`. Cette
sonde est **hors moteur de production** ; elle documente l'évaluation
d'ADR-001.

## 9. Archiver les résultats de test

Chaque campagne de verification est archivee dans un dossier date :

```bash
DEST=tests/results/$(date +%F)-<mission>
mkdir -p "$DEST"
.venv/bin/python -m pytest -v --junitxml="$DEST/junit.xml" > "$DEST/pytest-console.txt" 2>&1
.venv/bin/python -m coverage run --source=src/etatmajor -m pytest -q > "$DEST/pytest-coverage-run.txt" 2>&1
.venv/bin/python -m coverage report -m > "$DEST/coverage-report.txt"
.venv/bin/python -m coverage json -o "$DEST/coverage.json"
```

Les audits d'architecture et de performance produisent leurs preuves dans
`docs/audit/evidence/` :

```bash
.venv/bin/python scripts/audit_inventory.py --output docs/audit/evidence
.venv/bin/python scripts/benchmark_replay.py --output docs/audit/evidence
```

Convention detaillee : `tests/results/README.md`.

## 10. Diagnostic

| Symptôme | Cause probable | Action |
| --- | --- | --- |
| `market data validation failed` | lignes invalides | lire la liste des anomalies (numéro de ligne) |
| `configuration file not found` | chemin relatif au mauvais répertoire | lancer depuis la racine du dépôt |
| `quantity ... exceeds the authorised maximum` | garde-fou du risque | vérifier `configs/simulation.toml` → `[risk]` |
| rapport vide / 0 ordre | stratégie sans signal sur le dataset | vérifier les index d'entrée/sortie |
| `no market for <symbol>` (sonde Nautilus) | type de barre incompatible | utiliser un bar type `LAST` |

## 11. Limites d'exploitation

* Le moteur est mono-instrument et mono-timeframe.
* Les coûts sont modélisés, non mesurés sur un carnet réel.
* Aucune métrique de performance (profit factor, drawdown…) n'est encore
  produite : c'est l'objet des Phases 7 et 8.
* La réconciliation avec un compte réel n'existe pas (Phase 9).

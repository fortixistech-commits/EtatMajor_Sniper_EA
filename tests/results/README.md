# Résultats de tests archivés

Chaque exécution de la suite de tests est archivée dans un dossier daté
`tests/results/<AAAA-MM-JJ>-<mission>/` afin que toute affirmation de
reproductibilité puisse être contrôlée sans réexécuter quoi que ce soit.

## Convention de nommage

```text
tests/results/
└── 2026-10-22-mission-0/
    ├── pytest-console.txt        sortie complète de pytest -v
    ├── pytest-coverage-run.txt   sortie de la couverture
    ├── junit.xml                 rapport JUnit (compatible CI / outils XML)
    ├── coverage-report.txt       couverture ligne par ligne
    └── coverage.json             couverture exploitable par programme
```

## Contenu obligatoire d'un dossier de résultats

| Fichier | Rôle |
| --- | --- |
| `pytest-console.txt` | sortie de `python -m pytest -v` (liste nominative des tests et statut) |
| `junit.xml` | rapport JUnit pour les chaînes d'outils |
| `coverage-report.txt` | couverture des modules (mesure de la solidité du socle) |
| `coverage.json` | même donnée, exploitable par programme |

## Commandes de production

```bash
DEST=tests/results/$(date +%F)-<mission>
mkdir -p "$DEST"

.venv/bin/python -m pytest -v --junitxml="$DEST/junit.xml" > "$DEST/pytest-console.txt" 2>&1
.venv/bin/python -m coverage run --source=src/etatmajor -m pytest -q > "$DEST/pytest-coverage-run.txt" 2>&1
.venv/bin/python -m coverage report -m > "$DEST/coverage-report.txt"
.venv/bin/python -m coverage json -o "$DEST/coverage.json"
```

Pour les audits d'architecture et de performance, les preuves sontversionnées
dans `docs/audit/evidence/` :

```bash
.venv/bin/python scripts/audit_inventory.py --output docs/audit/evidence
.venv/bin/python scripts/benchmark_replay.py --output docs/audit/evidence
```

## Règles

1. aucune exécution n'est supprimée : les résultats archivés sont des
   preuves d'audit ;
2. un résultat d'exécution est toujours accompagné de la version de code
   (branche + empreinte de commit) et de la commande exacte ;
3. un test qui échoue est conservé tel quel : la correction se fait dans le
   code, jamais dans l'archive.

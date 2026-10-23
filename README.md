# ETAT-MAJOR SNIPER EA

Laboratoire de simulation de marché, système d'évaluation de stratégies et
socle d'exécution destiné à MetaTrader 5.

> **État du projet : Phase 8 (cockpit et observabilité) livrée, porte G8.**
> Le dépôt contient un moteur de replay historique déterministe, un broker
> simulé contraint par l'instrument, une autorité de risque minimale, un
> détecteur de régimes explicable, une doctrine d'abstention/engagement
> qualifiée, une réconciliation ordres/fills/portefeuille bloquante, un
> Challenge Engine audité, un rapport de reproductibilité et un cockpit
> opérateur hors ligne. Aucun ordre réel n'est possible : le code n'ouvre
> aucune connexion réseau.

Le projet ne cherche pas à produire « le meilleur robot du marché ». Il
construit d'abord un environnement capable de démontrer objectivement si une
stratégie mérite d'être déployée.

**Ordre des priorités : intégrité des données → fidélité de la simulation →
exactitude du risque → validation statistique → robustesse opérationnelle →
production.**

---

## 1. Installation

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e ".[dev]"
```

Prérequis : CPython >= 3.11 (validé sur 3.13 / aarch64). Le moteur de replay
n'a **aucune dépendance runtime** : uniquement la bibliothèque standard.

Évaluation de NautilusTrader (moteur candidat, environnement isolé) :

```bash
./scripts/run_nautilus_probe.sh      # crée .venv-nautilus avec nautilus_trader==1.231.0
```

## 2. Lancer la simulation

```bash
# 1. valider les données (rapport de qualité, catalogue et provenance)
.venv/bin/python -m etatmajor.cli validate \
    --data data/sample_eurusd_1m.csv \
    --config configs/simulation.toml \
    --instrument-catalog configs/instruments.toml \
    --broker-id mt5_demo \
    --provenance configs/data_provenance.sample.toml

# 2. rejouer l'historique
.venv/bin/python -m etatmajor.cli replay \
    --data data/sample_eurusd_1m.csv \
    --config configs/simulation.toml \
    --instrument-catalog configs/instruments.toml \
    --broker-id mt5_demo \
    --provenance configs/data_provenance.sample.toml \
    --report artifacts/report.json \
    --journal artifacts/journal.jsonl

# ou, en une commande
./scripts/run_replay.sh
```

La sortie console est un résumé lisible ; `artifacts/report.json` est le
rapport machine (contrat de la Phase 2) et `artifacts/journal.jsonl` la trace
d'audit de chaque décision.

Pour rejouer la doctrine Sniper complète (intelligence de marché, régime,
confluence, planification), ajouter `--strategy sniper`. Le défaut reste la
stratégie de démonstration, qui produit l'artefact de référence.

## 3. Inspecter avec le cockpit

Le cockpit est une vue **lecture seule** du rapport et de son journal. Il ne
rejoue rien, n'appelle aucun service et ne lit pas l'horloge murale.

```bash
.venv/bin/python -m etatmajor.cli cockpit \
    --report artifacts/report.json \
    --journal artifacts/journal.jsonl \
    --html artifacts/cockpit.html \
    --json artifacts/cockpit.json

# mode strict : toute anomalie ou avertissement produit un code retour 3
.venv/bin/python -m etatmajor.cli cockpit \
    --report artifacts/report.json \
    --journal artifacts/journal.jsonl \
    --strict
```

Le cockpit vérifie l'empreinte du rapport, la continuité des séquences du
journal, l'identité de session, le dernier événement, la réconciliation et le
verdict de challenge. Le HTML est autonome (CSS inline, aucun script).

## 4. Tests

```bash
.venv/bin/python -m pytest -q          # suite complète
.venv/bin/python -m pytest tests/unit -q
```

Les tests vérifient des valeurs et des invariants, pas seulement l'absence
d'exception : deux exécutions identiques, exécution différée, rejet des
données malformées, application du spread/slippage/commissions, invariance du
portefeuille après un refus du risque, politique de fin de replay, intégrité
du cockpit et absence d'accès réseau.

## 5. Organisation

```text
EtatMajor_Sniper_EA/
├── configs/          configuration TOML (simulation, risque,challenges)
├── data/             datasets (sample synthétique versionné)
├── docs/             architecture, décisions, rapport de phase, sécurité
├── scripts/          génération de données, sondes, commandes reproductibles
├── src/etatmajor/    moteur (voir docs/ARCHITECTURE.md)
└── tests/            unit / integration / acceptance
```

Le package suit la séparation des responsabilités :

| Module | Rôle |
| --- | --- |
| `etatmajor.core` | horloge, types, erreurs, événements, journal, configuration |
| `etatmajor.data` | catalogue d'instruments, provenance, chargement et validation OHLC |
| `etatmajor.replay` | moteur de replay, politique de fin de replay |
| `etatmajor.execution` | broker simulé, comptabilité du portefeuille |
| `etatmajor.risk` | contrat et implémentation minimale de l'autorité de risque |
| `etatmajor.strategies` | contrat de stratégie et stratégie de démonstration |
| `etatmajor.sniper` | Market Intelligence, contexte, setup, planification |
| `etatmajor.reporting` | rapport JSON et résumé console |

## 6. Règle anti-look-ahead

Un signal calculé à la clôture d'une bougie n'est **jamais** exécuté sur
cette bougie. Le moteur :

1. délivre la bougie `i` à la stratégie à sa clôture ;
2. soumet les propositions à l'autorité de risque à cet instant ;
3. exécute les ordres acceptés **à l'ouverture de la bougie `i+1`**.

Le prix d'exécution est donc l'ouverture de la bougie suivante, une valeur
inconnue au moment de la décision. Ce comportement est vérifié par test, y
compris sur un dataset comportant un gap de prix.

## 7. Documentation

| Document | Contenu |
| --- | --- |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | architecture, modèle temporel, hypothèses, limites |
| [docs/ARCHITECTURE_DECISIONS.md](docs/ARCHITECTURE_DECISIONS.md) | décisions structurantes (dont l'évaluation de NautilusTrader) |
| [docs/PHASE2_REPORT.md](docs/PHASE2_REPORT.md) | rapport de livraison de la Phase 2, preuves et risques résiduels |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | procédures d'exploitation, interprétation des rapports |
| [docs/SECURITY.md](docs/SECURITY.md) | secrets, cloisonnement simulation/production |
| [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) | état d'avancement par phase |
| [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) | plan des phases suivantes |

## 8. Avertissement

Les résultats produits par ce dépôt sont des **simulations**. Ils ne
constituent ni une garantie de performance, ni une preuve de rentabilité, ni
une autorisation de passer en production. Toute stratégie doit être validée
sur données hors échantillon, en simulation de scénario défavorable, puis en
paper trading, avant toute activation en production.

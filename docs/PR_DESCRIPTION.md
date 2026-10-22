# Proposition de Pull Request — Phase 2 : moteur de replay déterministe

**Base :** `main` · **Head :** `feat/phase-2-replay-engine`

---

## Résumé

Première livraison exécutable du projet ETAT-MAJOR SNIPER EA : un moteur de
replay historique **déterministe**, testé et documenté, qui rejoue des données
OHLC, applique un modèle d'exécution explicite (spread, slippage,
commissions), fait passer chaque proposition d'ordre par une **autorité de
risque** indépendante, tient une comptabilité vérifiable et produit un rapport
JSON reproductible accompagné d'un journal d'audit.

**Aucun ordre réel n'est possible** : aucun SDK broker n'est importé, aucune
connexion réseau n'est ouverte (vérifié par test).

La branche est un **empilement de commits de portée limitée** (fondation,
modèles, données, exécution, risque, moteur, tests, documentation).

## Architecture en bref

```text
CSV → data.loader (validation) → replay.engine (horloge simulée)
        → strategies (contrat)  → risk.governor (veto)  → execution.broker
        → execution.accounting (comptabilité) → reporting.report + journal
```

Modèle temporel retenu (règle anti-look-ahead du cahier des charges) :

```text
clôture(i) → décision → autorisation du risque → soumission
           → ouverture(i+1) → exécution
```

## Points d'attention pour la revue

1. **Modèle d'exécution.** NautilusTrader 1.231.0 a été installé et testé
   (`scripts/probe_nautilus.py`). Sur un dataset avec gap, il exécute au
   cours de **clôture de la bougie de signal** — le biais interdit par le
   cahier des charges. Le moteur interne exécute à l'**ouverture de la bougie
   suivante**. Décision : ADR-001.
2. **Politique de fin de replay** explicite (`CLOSE_AT_LAST_PRICE` par
   défaut), annoncée dans le rapport.
3. **Rapport sans donnée d'environnement** (ni chemin absolu, ni horodatage) :
   deux exécutions donnent des rapports identiques octet pour octet.

## Commandes exécutées

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

.venv/bin/python -m pytest -q
# 104 passed

.venv/bin/python -m etatmajor.cli validate \
    --data data/sample_eurusd_1m.csv --config configs/simulation.toml
# 240 bar(s) acceptées, 0 erreur

.venv/bin/python -m etatmajor.cli replay \
    --data data/sample_eurusd_1m.csv --config configs/simulation.toml \
    --report artifacts/report.json --journal artifacts/journal.jsonl
```

## Résultats de tests

`104 passed` — les 9 assertions obligatoires de la mission sont couvertes par
des tests vérifiant des **valeurs**, pas seulement l'absence d'exception :
reproductibilité (y compris inter-processus), exécution différée, rejet des
données malformées avec numéro de ligne, application exacte du
spread/slippage/commissions, invariance du portefeuille après refus du risque,
politique des ordres en attente, réconciliation comptable de fin de replay,
fonctionnement sans réseau, non-régression.

## Exemple de rapport

`artifacts/example_report.json` (extrait) :

```json
{
  "symbol": "EURUSD",
  "timeframe": "1m",
  "bars": 240,
  "orders": { "total": 2, "by_status": { "FILLED": 2 } },
  "executions": { "total": 2, "volume": 20000.0 },
  "transactions": 2,
  "fees": 1.4,
  "account": {
    "initial_capital": 100000.0,
    "final_equity": 100005.31,
    "net_pnl": 5.31,
    "currency": "USD"
  },
  "rejections": { "risk_count": 0, "broker_count": 0 },
  "end_of_replay_policy": "CLOSE_AT_LAST_PRICE",
  "simulation_only": true
}
```

> Ce chiffre provient d'une **simulation** sur un jeu de données synthétique et
> ne constitue en aucun cas une démonstration de rentabilité.

## Limites restantes

- ambiguïté intra-bougie (stop vs cible) : hypothèse conservatrice, Phase 4 ;
- swaps et financement overnight absents : Phase 4 ;
- marge, levier, perte journalière, drawdown, profils de challenge : Phase 5 ;
- ingestion de données réelles et stockage Parquet : Phase 3 ;
- métriques de performance et scénarios de stress : Phase 7 ;
- intégration MT5 et paper trading : Phase 9.

## Statut des critères d'acceptation

| Critère | Statut |
| --- | --- |
| Tests au vert dans un environnement propre | Satisfait (104 passed) |
| Commandes documentées (installation, tests, lancement) | Satisfait |
| Assertions critiques couvertes | Satisfait (9/9) |
| Capital final et PnL cohérents | Satisfait (invariants testés) |
| Coûts non comptés deux fois | Satisfait (test dédié) |
| Limites documentées | Satisfait (`docs/ARCHITECTURE.md` §9) |
| Aucun ordre réel | Satisfait (aucun SDK broker, aucun socket) |
| Fichiers, tests, risques détaillés | Satisfait (`docs/PHASE2_REPORT.md`) |

## Merge

**Ne pas fusionner sans l'audit du chef de projet.**

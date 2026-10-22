# Proposition de Pull Request — MISSION 0 : audit factuel du dépôt

**Base :** `feat/phase-2-replay-engine` · **Head :** `feat/mission-0-audit`

---

## Résumé

Audit **factuel** du dépôt, établi sur preuves exécutables et sans aucune
modification fonctionnelle. Trois.outils reproductibles sont ajoutés
(inventaire statique, mesure de performance, archivage des résultats de test),
trois documents de cadrage sont produits (rapport d'audit, architecture
courante, backlog de corrections) et l'état réel du projet est comparé à la
feuille de route.

**Cette PR ne crée aucune capacité nouvelle.** Elle établit ce qui existe,
ce qui fonctionne, ce qui ne fonctionne pas, et dans quel ordre corriger.

## Ce que l'audit établit

| Objet | Résultat |
| --- | --- |
| Tests | **104 passed**, couverture **86 %** des instructions de `src/etatmajor` |
| Dépendances circulaires | **0** |
| Fonctions vides / stubs | **0** |
| Capacité d'envoi d'ordre réel | **impossible** (aucun import réseau, aucun SDK broker) |
| Conformité Mission 1 (socle) | ~55 % |
| Conformité Mission 2 (replay) | ~80 % |
| Conformité Mission 3 (données) | ~30 % |
| Conformité Mission 4 (exécution) | ~50 % |
| Missions 5 à 16 | absentes (RiskGovernor squelette, aucun Challenge Engine, aucun Sniper Engine, aucun cockpit, aucun adaptateur MT5) |

## Défauts majeurs identifiés (avec preuve)

1. **AUDIT-D1 — rejeu quadratique** (`replay/engine.py:205`) : la copie de
   l'historique visible à chaque bougie coûte 43,0 µs/bougie à 240 bougies
   contre 114,2 µs/bougie à 20 000 ; projection ~95 min pour 1 M de bougies.
   Cause : `visible_bars=tuple(self.dataset.bars[: index + 1])`.
2. **AUDIT-D10** — aucun catalogue d'instruments (fidélité d'exécution non
   garantie, Porte G4).
3. **AUDIT-D11 / D12** — aucun Challenge Engine et RiskGovernor sans aucune
   conscience des règles de challenge : le simulateur ne peut pas encore
   répondre à « aurions-nous respecté les règles ? ».

Défauts mineurs : `on_stop` jamais appelé, expiration de signal non appliquée,
pas de volume non appliqué, mode codé en dur, exceptions typées jamais levées,
9 symboles d'API morte, fingerprint recalculé trois fois, détection de trous
approximative.

## Choix de langage, décidé par la mesure

| Technologie | Décision | Justification mesurée |
| --- | --- | --- |
| Python | conservée | 1,14 k instructions, 86 % de couverture, 104 tests |
| Numba | écartée | le goulot est l'allocation mémoire, pas le calcul |
| Rust | écartée | 8 700–25 000 bougies/s suffisent ; le goulot est algorithmique |
| MQL5 | non utilisé | aucun composant ne doit résider dans MT5 avant la Mission 8 (lecture seule) |

## Fichiers

```text
scripts/audit_inventory.py            outil d'inventaire AST (lecture seule)
scripts/benchmark_replay.py            mesure de débit et mémoire
docs/audit/INITIAL_AUDIT.md           rapport d'audit (preuves, matrice, risques)
docs/audit/BACKLOG.md                 corrections C1..C9
docs/audit/NEXT_MISSION_PROPOSAL.md   mission suivante proposée + 11 critères
docs/architecture/CURRENT_ARCHITECTURE.md  architecture réellement existante
docs/audit/evidence/inventory.json    preuve : inventaire, graphe, API morte
docs/audit/evidence/benchmark.json    preuve : débit, temps, mémoire
docs/audit/evidence/profile-10k-bars.txt  preuve : profil cProfile
tests/results/2026-10-22-mission-0/  preuve : tests + couverture archivés
tests/results/README.md               convention d'archivage des résultats
docs/OPERATIONS.md, docs/PROJECT_STATUS.md  mise à jour
```

## Commandes exécutées

```bash
python scripts/audit_inventory.py --output docs/audit/evidence
python scripts/benchmark_replay.py --output docs/audit/evidence
python -m pytest -v --junitxml=tests/results/2026-10-22-mission-0/junit.xml
python -m coverage run --source=src/etatmajor -m pytest -q
python -m coverage report -m
```

```
104 passed in 2.67s
TOTAL  1141 statements, 160 missed, 86%
```

## Sortie de benchmark (preuve du défaut D1)

```text
    240 bars | replay    0.010s |    23,231 bars/s |    43.0 us/bar
  5,000 bars | replay    0.197s |    25,429 bars/s |    39.3 us/bar
 10,000 bars | replay    0.662s |    15,111 bars/s |    66.2 us/bar
 20,000 bars | replay    2.285s |     8,753 bars/s |   114.2 us/bar
```

## Limites de cet audit

* l'audit porte sur l'état **local** du dépôt : la branche Phase 2 n'est pas
  sur GitHub (blocage d'accès décrit en §2.1 du rapport) ;
* la conformité au CDC est évaluée sur les **exigences écrites** ; les
  critères non chiffrables du CDC (qualité d'un plan de mission, réalisme
  d'une configuration Sniper) ne sont pas auditables par des tests ;
* aucune règle du challenge The5ers n'a été vérifiée : c'est hors périmètre de
  la Mission 0 et c'est le premier obstacle à la Mission 7 ;
* l'audit ne préjuge pas desorrectifs : il établit des faits et des ordres
  possibles.

## Décision demandée

**VALIDÉ POUR REVUE** — puis approbation de l'ordre **C1 → C2 → C3**
(corrections du socle, sans nouvelle capacité), et arbitrage du profil
The5ers de référence.

**Ne pas fusionner sans l'audit du chef de projet.**

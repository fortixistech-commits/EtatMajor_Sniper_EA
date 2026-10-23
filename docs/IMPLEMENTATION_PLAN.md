# Plan d'implémentation

Phases 3 à 10, avec les jalons techniques et les conditions de passage. Le
détail de chaque phase figure dans le cahier des charges ; ce document décrit
**ce qui sera construit dans le dépôt existant**, et non un redécoupage.

---

## Phase 3 — Ingestion et qualité des données

**Extension du code existant**

| Élément | Extension |
| --- | --- |
| `data/loader.py` | adders CSV à date, exports MT5 (`.csv` et `.txt` MetaQuotes), horodatages epoch MT5, colonne `spread`/`real_volume` optionnelle |
| `data/validation.py` | détection de trous par motif (session, jours fériés), détection de valeurs aberrantes (z-score local), rapport de qualité versionné (JSON) |
| `data/warehouse` | stockage brut (immuable) + stockage normalisé **Parquet** + empreinte SHA-256 par dataset |
| `data/instruments.py` | fiche instrument : digits, lot size, tick value, min/max volume, pas de volume, horaires, swaps, commissions, marge — versionnée par broker |
| `cli.py` | commande `ingest` : import → validation → rapport de qualité → refus du démarrage si la qualité est insuffisante |

**Jalon technique.** Import du même fichier deux fois : aucun doublon non
maîtrisé. Chaque simulation référence l'empreinte du dataset utilisé.

**Condition de passage.** Pipeline testé sur un dataset réel (export MT5),
rapport de qualité exploitable, instruments documentés par broker.

## Phase 4 — Replay historique et modèle d'exécution

| Élément | Extension |
| --- | --- |
| `execution/broker.py` | modèle de carnet simplifié (niveaux), fill models partiels, latence, gaps, stops intra-bougie ordonnés conservativement, scénarios de rejet et de perte de connexion |
| `execution/accounting.py` | swaps et financement overnight, frais tiers (commission de tiers) |
| `core/events.py` | événements de carnet (bid/ask), ordre partiel |
| `data/quality` | détection automatique d'ambiguïté intra-bougie et signalement dans le rapport |

**Jalon technique.** Matrice de tests d'exécution : gap à travers un stop,
spread élargi, latence, rejet, ordre partiellement rempli, absence de donnée
pendant une bougie.

**Décision à documenter (ADR).** Le traitement de l'ambiguïté intra-bougie :
données tick, ou hypothèse conservatrice explicite. Le rapport doit indiquer
la règle appliquée pour chaque opération.

## Phase 5 — Moteur de risque et challenge prop firm

| Élément | Extension |
| --- | --- |
| `risk/governor.py` | perte journalière, perte globale, drawdown statique et trailing, exposition corrélée, limites de volume et de marge, contrôle des ordres en attente, mode dégradé |
| `risk/challenge.py` | profils de challenge versionnés (capital, objectif, limites, fuseau, heure de réinitialisation, jours de trading, conditions de réussite/échec) |
| `risk/incidents.py` | gestion d'incident : blocage des entrées, politique sur positions ouvertes, réarmement explicite |
| `configs/prop_firms/` | un profil par programme, avec source officielle et date de vérification |

**Jalon technique.** Tests aux seuils exacts (juste avant, au seuil, juste
après) pour chaque limite. Un signal valide doit pouvoir être refusé.

**Point de vigilance.** Les règles exactes des programmes de prop firm
doivent être vérifiées dans la documentation officielle et datées. Aucune
règle ne doit être supposée.

## Phase 6 — Doctrine Sniper et interface des stratégies

| Élément | Extension |
| --- | --- |
| `sniper/context_filter.py` | régime, session, données manquantes, événements macro |
| `sniper/setup_detector.py` | détection de configurations, résultat mesurable |
| `sniper/trade_planner.py` | sens, entrée, invalidation, ratio rendement/risque, taille, coûts, hypothèses |
| `sniper/risk_authorization.py` | transmission au governor, respect obligatoire du verdict |
| `sniper/execution_review.py` | suivi des confirmations, des sorties, enregistrement du résultat |
| `strategies/base.py` | enrichissement du contrat : expiration du signal, références de données, justification codifiée |

**Jalon technique.** Une stratégie de référence Sniper traverse la chaîne
complète sans ordre réel, et l'abstraction d'un signal reste explicite
(abstention ≠ signal vide).

## Phase 7 — Évaluation du comportement et stress

| Élément | Extension |
| --- | --- |
| `evaluation/behavior.py` | qualité de sélection, fréquence d'abstention, taux de refus par le risque, respect des invalidations, entrées tardives, réactivité aux données dégradées |
| `evaluation/scenarios.py` | scénarios de stress (spreads, latence, gaps, rejets, interruptions) et trajectoires synthétiques (tendances, ranges, changements de volatilité) |
| `evaluation/seed.py` | reproductibilité par graine et par configuration |
| `reporting/` | rapports séparant explicitement données réelles et synthétiques |

**Jalon technique.** Les scénarios défavorables sont visibles dans les
rapports, jamais exclus.

## Phase 8 — Backtests, robustesse et sélection

> **Note d'exécution (2026-10-22).** La Phase 8 livrée est le cockpit et
> l'observabilité. Les travaux de ce chapitre deviennent la Phase 9 ;
> l'adaptateur MT5 passe en Phase 10. Ce plan reste la référence
> méthodologique.

| Élément | Extension |
| --- | --- |
| `reporting/metrics.py` | profit net, espérance, profit factor, drawdown, nombre d'opérations, gain/perte moyens, pertes extrêmes, exposition, résultats par instrument/session/régime |
| `evaluation/robustness.py` | séparation entraînement / validation / test, sensibilité aux paramètres, Monte-Carlo, détection d'optimisation excessive |
| `reporting/validation.py` | dossier de validation signé, critères d'acceptation **définis avant** les tests |

**Règle.** Le taux de réussite seul n'est pas une métrique de validation
suffisante.

## Phase 9 — Adaptateur MT5 et paper trading

| Élément | Extension |
| --- | --- |
| `execution/adapters/mt5.py` | adaptateur distinct du moteur de stratégie : connexion, ordres, confirmations, reconnexion, réconciliation compte/ordres/positions |
| `execution/adapters/base.py` | contrat d'adaptateur + environment de test hors MT5 |
| `replay/incident.py` | scénarios de perte de connexion, d'état de compte inconnu, de doublon d'ordre |
| `safety/emergency.py` | arrêt d'urgence, blocage des entrées, politique de reprise |

**Jalon technique.** Reconnexion sans doublon ; le governor fonctionne aussi
en mode connecté ; l'arrêt d'urgence bloque les entrées.

## Phase 10 — Préparation et activation de la production

| Élément | Extension |
| --- | --- |
| `safety/production.py` | préconditions bloquantes, autorisation humaine explicite, mode par défaut = simulation |
| `safety/audit.py` | journalisation persistante, traçabilité des opérations, revue |
| `docs/OPERATIONS.md` | procédures de démarrage, d'arrêt, de reprise, de retour en mode sécurisé |

**Règle.** La production ne s'active jamais par défaut, ni après
installation, ni après redémarrage, ni après changement de configuration.

---

## Séquencement

```text
3 ──▶ 4 ──▶ 5 ──▶ 6 ──▶ 7 ──▶ 8 ──▶ 9 ──▶ 10
 │      │      │      │      │      │      │      │
 └──────┴──────┴──────┴──────┴──────┴──────┴──────┘
        audit du chef de projet à chaque jalon
```

Chaque phase se termine par un compte rendu (implémentation, fichiers,
décisions, tests, limites, commandes de reproduction, risques, statut des
critères) et attend une validation avant la suivante.

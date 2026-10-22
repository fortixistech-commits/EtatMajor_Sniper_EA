# Sécurité, fiabilité et qualité

Exigences applicables à toutes les phases. État à la fin de la Phase 2.

---

## 1. Sécurité

| Exigence | État Phase 2 | Preuve |
| --- | --- | --- |
| Aucun secret dans Git | Respecté | `.gitignore` exclut `.env`, `*.local.toml`, `secrets/`, `*.key`, `*.pem` ; `.env.example` ne contient que des clés vides |
| Aucune opération réelle au démarrage | Respecté | aucun SDK broker importé ; aucun ordre possible : le moteur ne produit que des `Fill` en mémoire |
| Configurations de production distinctes | Respecté | les configurations existantes sont exclusivement des configurations de laboratoire (`mode = LABORATORY` dans le rapport) |
| Identifiants vérifiés avant connexion | Non applicable | aucune connexion n'existe |
| Données importées traitées comme non fiables | Respecté | validation stricte : types, positifs, doublons, ordre, cohérence OHLC, numéro de ligne ; les fichiers externes sont des entrées non fiables |
| Dépendances épinglées et auditées | Respecté | le moteur n'a **aucune dépendance runtime** ; `nautilus_trader==1.231.0` est épinglé dans l'extra optionnel `nautilus` |
| Actions critiques journalisées | Respecté | journal des événements : signal, verdict, soumission, exécution, frais |

## 2. Cloisonnement simulation / production

Ce cloisonnement est une exigence structurante du projet (Phase 10) et il est
**préparé** dès maintenant :

* le mode actif est écrit dans chaque rapport (`mode`, `simulation_only`) ;
* aucun module du dépôt n'importe `MetaTrader5`, `requests` ou une autre
  bibliothèque de connexion ;
* la couche d'exécution ne possède qu'un adaptateur simulé ; un adaptateur
  broker réel devra être un composant **distinct**, injecté, et interdit par
  défaut ;
* la production exigera une autorisation explicite et distincte (à venir,
  Phase 10) : le mode réel ne pourra pas être activé par un simple
  redémarrage.

## 3. Fiabilité

| Exigence | État Phase 2 |
| --- | --- |
| Erreurs explicites et traçables | Hiérarchie d'exceptions dédiée (`core.errors`), messages préfixés par le composant, anomalies de données localisées par ligne |
| États d'ordres et de positions non inventés | Le broker ne produit un remplissage qu'en présence d'une règle d'exécution explicite ; aucun état n'est supposé |
| Redémarrage commencé par une réconciliation | Non applicable en Phase 2 (aucun état persistant) ; à traiter en Phase 9 |
| Panne de données ou de risque n'autorise jamais une entrée | Une donnée invalide arrête le chargement ; un risque en panne ne peut pas autoriser (le governor est requis) |
| Fermeture et réduction du risque selon une politique distincte | La fermeture de fin de replay est une politique explicite, journalisée et distincte d'une nouvelle entrée |

## 4. Tests

| Type | Implémenté | Emplacement |
| --- | --- | --- |
| Unitaires (calculs) | Oui | `tests/unit/` |
| Intégration (flux entre composants) | Oui | `tests/integration/` |
| Acceptation (parcours complet) | Oui | `tests/acceptance/` |
| Régression sur résultats de référence | Oui | `tests/acceptance/test_cli.py::test_the_repository_shipped_example_report_is_consistent` compare le rapport versionné à une exécution fraîche |
| Propriétés (invariants critiques) | Oui | invariants de comptabilité, contrôles d'incohérence du risk governor |
| Performance | Non | volontairement différé jusqu'à validation fonctionnelle |

Aucune optimisation de concurrence, de parallélisme ou de Rust n'a été
entreprise : le moteur est séquentiel et déterministe par construction.

## 5. Qualité

* types complets sur les modules publics (`from __future__ import annotations`
  et annotations systématiques) ;
* aucune dépendance runtime ;
* code sans commentaire superflu, noms explicites, méthode de
  déterministe ;
* configuration centralisée et validée au démarrage : une configuration
  invalide arrête le programme avec un message Actionable.

## 6. Gestion des incidents

| Incident | Réponse immédiate | Trace |
| --- | --- | --- |
| Résultat de simulation contesté | rejouer avec la même configuration et comparer `report_fingerprint` | rapport + journal |
| Ordre sans exécution | consulter `journal.jsonl`, filtrer `ORDER_SUBMITTED` puis `ORDER_REJECTED` | journal |
| Doublon de timestamp dans les données | `validate` liste la ligne fautive | rapport de qualité |
| Comportement incohérent de la stratégie | vérifier qu'elle ne lit que `context.visible_bars` | revue de code + test `test_strategy_cannot_observe_future_bars` |

## 7. Principes non négociables

1. Aucun résultat de simulation n'est présenté comme une garantie.
2. Aucun test n'est assoupli pour faire passer une fonctionnalité.
3. Aucun défaut critique de gestion des ordres ou du risque n'est laissé
   ouvert en fin de phase.
4. Aucune décision d'architecture n'est implicite : elle est écrite dans
   `docs/ARCHITECTURE_DECISIONS.md`.

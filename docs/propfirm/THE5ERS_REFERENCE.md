# Référence The5ers — High Stakes New, compte 2 500 USD

**Statut :** PROFIL DE TRAVAIL — **DRAFT**, non utilisable pour déclarer une
simulation conforme
**Date de vérification :** 2026-10-22
**Source :** pages officielles The5ers, relevées par le chef de projet
**Fichier de profil associé :**
`configs/prop_firms/the5ers_high_stakes_new_2500.draft.yaml`

> **Règle appliquée (CDC, Mission 7 et principe 4).** Aucune règle de
> challenge n'est supposée ni laissée implicite. Les paramètres ci-dessous
> sont ceux **affichés publiquement** par The5ers au 22 octobre 2026. Ce sont
> des valeurs de travail datées, pas un engagement contractuel. Un profil
> incomplet ne peut pas servir à conclure : le Challenge Engine doit refuser
> de statuer tant que `profile_status` n'est pas `VERIFIED`.

---

## 1. Programme retenu

| Élément | Valeur |
| --- | --- |
| Programme | The5ers **High Stakes** |
| Variante | **New** (et non *Classic*) — la cible de la première étape diffère |
| Taille de compte | **2 500 USD** |
| Plateforme indiquée | **MT5 Hedge** |
| Durée maximale | **Illimitée** |
| Frais affichés | **19 USD** |

> La distinction New / Classic est consignée ici parce que les règles ne sont
> pas interchangeables entre les deux variantes.

## 2. Paramètres relevés (2026-10-22)

| Paramètre | Valeur affichée | Converti sur 2 500 USD |
| --- | --- | --- |
| Objectif étape 1 | 10 % | **250 USD** |
| Objectif étape 2 | 5 % | **125 USD** |
| Perte quotidienne maximale | 5 % | **125 USD** |
| Perte totale maximale | 10 % | **250 USD** |
| Jours profitables minimum | 3 par étape | 6 au total (2 × 3) |
| Durée maximale | illimitée | — |
| Plateforme | MT5 Hedge | — |

**Sources officielles (relevées le 2026-10-22) :**

* programme : <https://the5ers.com/high-stakes/>
* règles générales du programme : <https://the5ers.com/faqs/what-are-the-general-rules-for-the-high-stakes-program/>

Ces liens sont à re-vérifier avant toute campagne de référence : les règles
peuvent changer.

## 3. Points encore à documenter (verrous)

Ces règles **ne sont pas** dans les valeurs affichées. Elles ne doivent pas
être déduites : elles doivent être relevées dans les conditions officielles,
ou confirmées par écrit.

| # | Point à établir | Enjeu | Traitement tant qu'il est ouvert |
| --- | --- | --- | --- |
| V1 | **Méthode de calcul de la perte quotidienne** : sur le solde (statique) ou sur l'equity (trailing) ? | change le verdict d'une campagne entière | les deux interprétations sont évaluées, **la plus restrictive l'emporte** (voir §5) |
| V2 | **Heure et fuseau de réinitialisation** du compteur quotidien | détermine le rattachement d'une perte à une journée | hypothèse explicite à documenter dans le rapport, ou règle refusée |
| V3 | **Définition d'un « jour profitable »** (PnL > 0 net de frais sur la journée ? sur l'equity ?) | condition de validation des deux étapes | compte conservatrice : PnL réalisé net > 0 |
| V4 | **Traitement des frais** de 19 USD : déduits du capital de référence, ou facturés à part ? | modifie la base de calcul de toutes les limites | hypothèse la plus défavorable retenue : capital de référence = 2 500 − 19 |
| V5 | **Report entre les étapes** : le capital de l'étape 2 est-il 2 500 USD ou 2 750 USD (objectif 1 atteint) ? | change les seuils de l'étape 2 | hypothèse : capital de référence de l'étape 2 = 2 500 USD (le plus restrictif) |
| V6 | **Ouverture simultanée de positions** et consolidation des pertes | peut agréger des pertes au-delà de la limite quotidienne | hypothèse la plus restrictive : agrégation de toutes les positions du compte |
| V7 | **Heures de trading / news trading** restrictions éventuelles | peut interdire des engagements | filtre configurable, non activé tant que la règle n'est pas connue |
| V8 | **Confirmation écrite d'autorisation** de l'EA et de l'architecture de réplication | condition préalable à toute évaluation réelle | **bloquant** pour la Mission 14 |

## 4. Règles générales à examiner avant toute utilisation réelle

Les conditions générales The5ers, mises à jour le **20 octobre 2026**, doivent
être examinées avant toute utilisation réelle d'un Expert Advisor :

* confirmation écrite de l'autorisation de notre logiciel ;
* restrictions éventuelles sur le **copy trading** et sur la réplication
  d'une architecture de signal ;
* propriété du code source et obligations déclaratives ;
* conditions de remboursement, de passage à la phasefunded et retrait des
  frais.

Ce point est traité dans la Mission 14 (Évaluation réelle contrôlée) et il est
**bloquant** : aucune évaluation réelle ne peut être préparée avant d'avoir
ces éléments.

## 5. Principe de fonctionnement retenu pour les règles ambiguës

Le CDC impose : « Les paramètres inconnus ne doivent jamais être remplacés
silencieusement par des suppositions. »

Le profil déclare donc les règles ambiguës (V1 à V7) dans une section
`ambiguous_rules`. Le Challenge Engine les évalue **toutes**, en parallèle, et
retient le **verdict le plus défavorable** :

```text
verdict_final = le plus défavorable parmi les interprétations testées
```

Une campagne n'est déclarée `PASSED` que si **toutes** les interprétations
aboutissent à `PASSED`. Dans le rapport, chaque interprétation et son verdict
propre sont affichés : le rapport ne masque jamais une lecture favorable.

Ce mécanisme est un garde-fou, pas une approximation : il transforme une
incertitude documentaire en incertitude **visible** dans les résultats.

## 6. Ce que ce profil ne permet pas encore

* déclarer une campagne conforme (`profile_status: DRAFT`);
* remplacer une lecture des conditions officielles ;
* autoriser une évaluation réelle (V8 bloquant).

Il permet en revanche de **coder et tester** le Challenge Engine dès maintenant
(Mission 7) : les tests de frontière s'exécutent sur des profils de test
complets et synthetic, et le profil Draft sert de cas réel de documentation
des règles à établir.

## 7. Décisions demandées au chef de projet

1. confirmer que la cible reste **High Stakes New, 2 500 USD** (et non
   Classic, dont les paramètres diffèrent) ;
2. designating une source officielle pour V1 à V7 (pages officielles,
   conditions générales, ou confirmation écrite de la prop firm) ;
3. valider l'approche « interprétation la plus restrictive » pour les règles
   ambiguës (§5) ;
4. indiquer si une demande d'autorisation écrite pour l'EA doit être lancée
   dès maintenant, compte tenu du délai de réponse de The5ers.

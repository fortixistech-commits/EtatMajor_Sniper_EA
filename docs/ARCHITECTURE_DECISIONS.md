# Décisions d'architecture

Chaque décision structurante est enregistrée ici avec son contexte, les
options écartées et ses conséquences. Une décision n'est définitive que si
elle est réexaminée lors d'un jalon (Phase 4, Phase 5, Phase 9).

---

## ADR-001 — Moteur de simulation : moteur interne, NautilusTrader évalué en parallèle

**Statut :** accepté (Phase 2)

**Contexte.** Le cahier des charges désigne NautilusTrader comme candidat
principal pour le replay historique, l'évènementiel et l'exécution. Il exige
en parallèle un contrat de stratégie, une autorité de risque avec droit de
veto, une politique de fin de replay explicite et un rapport machine lisible
et déterministe.

**Évaluation réalisée.** NautilusTrader **1.231.0** a été installé dans un
environnement isolé et exécuté sur le dataset du dépôt
(`scripts/probe_nautilus.py`, artefacts `artifacts/nautilus_probe*.json`).

Résultats :

* installation et import fonctionnels sur CPython 3.13 (wheel manylinux
  `cp313-aarch64` disponible) ;
* cycle de vie complet en backtest : ordre → remplissage → position ;
* **remarque structurante** : sur un dataset comportant un gap, un ordre
  marché soumis pendant `on_bar` est exécuté **au cours de clôture de la
  bougie de signal** (1.10050), et non à l'ouverture de la bougie suivante
  (1.11000). C'est exactement le biais que le cahier des charges interdit
  (« un signal calculé à la clôture d'une bougie ne peut pas être exécuté
  rétroactivement sur cette même bougie »).

**Décision.** La Phase 2 est implémentée sur un **moteur interne**
(`etatmajor.replay`), sans dépendance runtime, qui :

* exécute les ordres à l'ouverture de la bougie suivante ;
* expose un contrat de stratégie, un contrat de risque injectable et une
  politique de fin de replay explicite ;
* produit un rapport JSON déterministe et un journal d'audit.

NautilusTrader reste un **candidat d'intégration à reconsidérer en Phase 4**
(composantes d'exécution, carnet d'ordres, fill models), pas le moteur
obligatoire de la Phase 2.

**Conséquences.** Le code de la Phase 2 est plus léger et testable sans
dépendance lourde, mais le moteur n'hérite pas de la maturité de
NautilusTrader (fill models, latence, carnet). Cette dette est repayée en
Phase 4, où le modèle d'exécution doit être approfondi de toute façon.

---

## ADR-002 — Le prix d'exécution d'un signal est l'ouverture de la bougie suivante

**Statut :** accepté (Phase 2)

**Contexte.** Une stratégie qui décide sur la clôture d'une bougie ne peut
pas être exécutée sur cette bougie : le prix de clôture n'est pas un prix
accessible à l'instant de la décision, et un gap rend le prix d'exécution
inconnu.

**Décision.** Le moteur applique la séquence :

```text
clôture(i) → décision de la stratégie → autorisation du risque
           → soumission → ouverture(i+1) → exécution
```

Les tests le vérifient sur un dataset **avec gap** : le prix d'exécution
n'est jamais le cours de clôture de la bougie de signal.

**Conséquences.** Les performances simulées sont volontairement plus
pessimistes qu'un exécution « à la clôture ». Un paramètre d'exécution plus
rapide (exécution intra-bougie sur le close) pourrait être introduit plus
tard, mais seulement avec un modèle de prix intra-bougie documenté.

---

## ADR-003 — Unités : quantités en unités instrument, prix en devise de cotation

**Statut :** accepté (Phase 2)

**Contexte.** Un CFD/Forex a une taille de contrat propre au broker. Mixing
les « lots » et les « unités » produit des erreurs de commissions et de
notionnel.

**Décision.** `quantity` est exprimée en **unités instrument**. `lot_size`
(défaut 100 000 pour un contrat FX) convertit une quantité en lots pour le
calcul des commissions. Le notionnel est `quantité × prix`. La taille de
contrat par broker fera l'objet d'une fiche instrument dédiée en Phase 3.

**Conséquences.** Une simulation doit connaître le `lot_size` du broker pour
interpréter les commissions. La valeur est explicite dans la configuration et
dans le rapport.

---

## ADR-004 — Politique de fin de replay explicite et versionnée

**Statut :** accepté (Phase 2)

**Décision.** Deux politiques, choisies en configuration :
`CLOSE_AT_LAST_PRICE` (défaut) et `MARK_TO_MARKET`. Les ordres en attente
sont toujours annulés. La politique utilisée figure dans le rapport.

**Conséquences.** Un rapport sans mention de la politique serait ambigu ;
elle est donc un champ obligatoire du contrat de rapport.

---

## ADR-005 — Le rapport ne contient aucune donnée d'environnement

**Statut :** accepté (Phase 2)

**Contexte.** L'empreinte du rapport sert de preuve de reproductibilité. Un
chemin absolu de fichier ou un horodatage de génération la rendrait inutilisable
d'une machine à l'autre.

**Décision.** Le rapport n'enregistre que le **nom** du fichier de données et
son empreinte SHA-256, jamais son chemin absolu ni l'heure de génération. La
comparaison se fait par `report_fingerprint`.

**Conséquences.** Un test d'acceptation vérifie qu'un rapport versionné dans
le dépôt correspond à une exécution fraîche (hors répertoire du dépôt).

---

## ADR-006 — Le journal d'événements est la source de vérité

**Statut :** accepté (Phase 2)

**Décision.** Le rapport est dérivé de l'état du moteur, mais c'est le
**journal** qui retrace la chaîne de décision (signal → verdict du risque →
soumission → exécution → frais). Toute décision doit pouvoir être reconstituée
à partir du journal seul.

**Conséquences.** Le journal est un contrat de long terme : il faudra y
ajouter les événements de Phase 5 (déclenchement de limite, drawdown) et de
Phase 9 (état broker, reconnexion) sans casser la lecture des anciens
journaux.

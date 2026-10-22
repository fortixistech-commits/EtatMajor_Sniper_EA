# Rapport de Phase D — Moteur SnipER (Mission 6)

> Resolution du virement. Explicitement nonaires 100% or else a sto
> pas, purpose peroclass peroclass, purpose perool.

Statut : **livree** — verifiee par la batterie de tests (340 tests, tous verts).

## Contenu

| Composant | Fichier | Role |
| --- | --- | --- |
| Reconnaissance de regime | `src/etatmajor/sniper/regime.py` | Classe la serie visible en `TREND_UP`, `TREND_DOWN`, `RANGE` ou `UNDEFINED`, avec un etat de volatilite (expansion / contraction / stable) et une confiance chiffree |
| Filtre de contexte | `src/etatmajor/sniper/context.py` | Dernier filtre de securite : session autorisee, spread borne, donnees fraiches, regime tendance. Une seule issue : autoriser ou refuser, avec motifs |
| Detection de configuration | `src/etatmajor/sniper/setup.py` | Detecte le repli vers la moyenne rapide suivi d'une reprise (setup B de la doctrine) et pose le niveau d'invalidation structurel |
| Planification de mission | `src/etatmajor/sniper/planner.py` | Traduit le setup detecte en `MissionPlan` complet : taille, stop, objectif, couts, duree, expiration. Un plan sans plan complet est refuse |
| Orchestration | `src/etatmajor/sniper/engine.py` | Enchaine reconnaissance -> contexte -> selection -> planification et rend une decision unique : engager (`TradeIntent`) ou s'abstenir (motifs journalises) |
| Adaptateur de strategie | `src/etatmajor/sniper/strategy.py` | Branche le moteur sur le contrat `Strategy` du rejeu ; il traduit la decision en `Signal` ou s'abstient, sans jamais modifier la decision |

## Regles appliquees

1. **L'abstention est un resultat valide.** Une serie sans tendance, hors
   session, avec un spread defavorable ou une donnee perimee ne produit
   **aucun** ordre : la decision d'abstention est record avec ses motifs
   (`SniperDecision.reasons`) et journalisable.
2. **Pas de plan, pas d'entree.** Le planificateur refuse de produire un
   `MissionPlan` si le risque demande est incompatible avec le pas de
   volume de l'instrument (`PlanningError`) ou si l'invalidation est situee
   sur le prix d'entree.
3. **Doctrine sans allied chicane.** Le detecteur de configuration exige,
   dans l'ordre : regime tendance, contact de la bougie courante avec la
   moyenne rapide, corps de reprise suffisant, invalidation structurelle.
4. **Aucune suppression de garde-fou.** Le `RiskGovernor` de la Phase C
   reste le seul decideur d'engagement reel ; le Sniper Engine se contente
   de **proposer**.

## Les tests

La doctrine est testee par des **valeurs**, pas par l'absence d'exception :

- `tests/unit/test_sniper_doctrine.py` — regime (tendance, range, donnees
  insuffisantes, volatilite, borne de bougies visibles), contexte (session,
  spread, fraicheur), planification (taille derivee du risque et de la
  distance au stop, refus des tailles trop petites), moteur (abstention
  hors tendance, plan complet quand le setup est valide), strategie
  (aucun signal si le moteur s'abstient, motifs enregistres).
- `tests/integration/test_sniper_integration.py` — la chaine complete dans
  le rejeu : une serie delibere sans tendance ne produit **aucun** ordre et
  **aucune** execution ; une serie construite pour produire exactement un
  setup (verifie numeriquement : 60 barres a +0.00005, repli sur l'EMA,
  reprise hossiere) produit un signal portant un `MissionPlan` complet
  (stop < entree, taille > 0, risque <= risque voulu, motif d'invalidation) ;
  le `RiskGovernor` peut refuser la proposition du Sniper sans aucune
  execution, capital intouchable.

## Corrections annexes

- `replay/engine.py` : le risque d'un ordre au marche est estime sur la
  cloture de la bougie, **jamais** sur le stop de protection. Avant cette
  correction, un ordre au marche porte un stop voyait son risque calcule
  a `quantity x |reference - stop| = 0` : le veto de risque par transaction
  du gouverneur etait silencieusement desactive pour de tels signaux.
- `core/events.py` : `Signal` transporte desormais un `plan` optionnel
  (`MissionPlan | None`) — le gouverneur et le journal peuvent faire la
  trace complete de la mission proposee.
- `sniper/regime.py` : confiance d'une classification `RANGE` corrigee :
  une marche plate est une range **sure**, une marche agitee une range
  de confiance faible (l'inversion precedente materialisait un
  comportement latent).
- `sniper/setup.py` : ternaire identique des deux cotes simplifie en
  booleen unique.
- `sniper/strategy.py` : un moteur injecte n'est plus mute ; parametre
  `max_signals_per_day` jamais utilise supprime.

## Verification

| Constitution d'essai | Resultat |
| --- | --- |
| `pytest tests` | **340 passed** |
| `python scripts/audit_inventory.py` | 0 cycle, 0 stub, 0 symbole non referencé, 0 exception jamais levee |
| `test_no_module_imports_a_higher_layer` | couche `sniper` ajoutee entre `strategies` et `replay` ; aucune importation ascendante |
| Artefacts de reference | `example_report.json` / `example_journal.jsonl` reproductibles (fingerprint `2c66af48eafaaa88`), test d'acceptation vert |

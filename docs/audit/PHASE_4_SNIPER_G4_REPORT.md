# Rapport - Phase 4 : qualification du Sniper Engine (G4)

**Projet :** ETAT-MAJOR SNIPER EA - **Date :** 2026-10-22
**Branche :** `fix/phase-c-corrections`
**Porte visee :** G4
**Verdict :** **PASS**, avec limites documentees.

---

## 1. Objectif

Verifier que la doctrine Sniper est **coherente et non contournable** :

- un setup n'est produit que dans une tendance, apres un repli confirme ;
- une reprise du mauvais cote de la moyenne est refusee ;
- le stop est structurel, du bon cote de l'entree ;
- un plan est complet ou n'existe pas ;
- une seule mission a la fois par instrument ;
- les gardes de confiance, structure, timeframe superieur et volatilite
  sont disponibles et explicites ;
- le RiskGovernor reste l'autorite finale.

## 2. Etat initial et defauts identifies

| Defaut | Risque | Correction |
| --- | --- | --- |
| Aucune politique de doctrine centralisee | seuils disperses, non auditables | `DoctrinePolicy` explicite |
| Reprise acceptee meme si la cloture restait du mauvais cote de l'EMA | entree contre le repli | cloture du bon cote exigee |
| `bars_in_pullback` valait toujours la fenetre | mesure trompeuse | comptage contigu des barres en interaction |
| Aucun blocage d'une seconde mission pendant une position ouverte | empilement d'ordres | garde `max_open_positions=1` |
| Aucun seuil de qualite de setup / confiance | setups faibles acceptes | gardes activables et testees |
| `min_quantity=0` pouvait produire un plan a quantite nulle | plan invalide | quantite strictement positive exigee |
| Geometrie du stop non verifiee dans le planificateur | stop du mauvais cote | refus explicite BUY/SELL |
| Parametres de planification invalides non refuses | division par zero / plan absurde | validation complete |

## 3. Fichiers modifies

| Fichier | Nature |
| --- | --- |
| `src/etatmajor/sniper/engine.py` | `DoctrinePolicy`, gardes, position ouverte, seuils |
| `src/etatmajor/sniper/setup.py` | cote de cloture, comptage du repli, geometrie |
| `src/etatmajor/sniper/planner.py` | validation des parametres et du sens du stop |
| `tests/unit/test_sniper_g4.py` | **nouveau** - 24 tests |

## 4. Decisions

### 4.1 Politique explicite

`DoctrinePolicy` regroupe les seuils :

| Champ | Defaut | Effet |
| --- | --- | --- |
| `min_confidence` | `0.0` | garde informative, activable |
| `min_setup_quality` | `0.0` | garde informative, activable |
| `require_structure_alignment` | `False` | exige une structure conforme au regime |
| `require_htf_alignment` | `False` | exige un timeframe superieur `ALIGNED` |
| `block_extreme_volatility` | `False` | suspend les engagements en volatilite extreme |
| `max_open_positions` | `1` | une mission a la fois par instrument |

Seule la garde de position est active par defaut : elle corrige un risque
d'empilement. Les autres seuils restent inactifs tant que G5/G9 ne les ont
pas calibres sur des donnees et des couts reels.

### 4.2 Setup

- La cloture de reprise doit etre **au-dessus** de l'EMA rapide pour un long,
  **en dessous** pour un short.
- L'invalidation reste le plus bas/haut du repli avec un tampon proportionnel
  a la bougie de reprise.
- `bars_in_pullback` compte les bougies contigues en interaction avec l'EMA,
  en remontant depuis la bougie courante.
- La qualite est bornee dans `[0, 1]` et n'est pas presentee comme une
  probabilite.

### 4.3 Plan

Le planificateur refuse desormais :

- un risque, un multiple R, un pas de volume ou une duree non positifs ;
- un cout unitaire ou une quantite minimale negatifs ;
- une quantite nulle ;
- un stop du mauvais cote de l'entree ;
- une distance d'invalidation nulle.

Le risque planifie reste `quantite x distance`, donc **inferieur ou egal** au
risque demande apres arrondi au pas de volume.

## 5. Resultats

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\test_sniper_g4.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

- Tests G4 : **24 passes**.
- Suite complete : **491 passes, 0 echec** (local, Windows, Python 3.14.0).
- Aucun artefact de replay modifie.

## 6. Criteres d'acceptation

| Critere | Etat | Preuve |
| --- | --- | --- |
| Setup long structurel complet | PASS | `test_a_valid_pullback_produces_a_structural_long_setup` |
| Setup short symetrique | PASS | `test_a_short_pullback_is_the_mirror_image` |
| Reprise du mauvais cote refusee | PASS | `test_a_resumption_closing_on_the_wrong_side_is_refused` |
| Corps de reprise minimal | PASS | `test_a_resumption_with_a_tiny_body_is_refused` |
| Stop structurel bufferise | PASS | `test_the_invalidation_is_below_the_pullback_low_with_a_buffer` |
| Plan complet et risque borne | PASS | `test_the_plan_is_complete_and_the_risk_never_exceeds_the_request` |
| Stop du bon cote | PASS | tests BUY/SELL dedies |
| Parametres invalides refuses | PASS | test parametre + quantite nulle |
| Une mission a la fois | PASS | `test_an_open_position_blocks_a_second_mission` |
| Gardes confiance / HTF / qualite / volatilite | PASS | quatre tests dedies |
| RiskGovernor non contourne | PASS | integration existante, aucun chemin direct d'execution |

## 7. Limites

1. Les seuils de politique ne sont pas encore exposes dans la configuration
   TOML ni dans la CLI ; ils sont injectables par code.
2. `max_open_positions` raisonne sur une position nettee par instrument :
   une valeur superieure a 1 n'a pas de sens avec le broker actuel.
3. La qualite du setup et la confiance ne sont pas calibrees statistiquement.
4. Les couts estimes ne sont pas inclus dans le risque planifie ; ils le
   seront en phase 6 (execution) et phase 5 (catalogue/contrat).
5. Le planificateur raisonne encore en unites d'instrument avec des valeurs
   par defaut ; le branchement au catalogue est la phase 5.
6. Aucune gestion de partage de position, de pyramiding ou de sortie
   partielle : hors doctrine actuelle.

## 8. Risques residuels

- **Seconde mission apres refus du risque** : si le gouverneur refuse, la
  position reste nulle et le moteur peut reproposer au bar suivant. C'est
  volontaire (retry explicite), mais doit etre borne en phase 7 par un
  compteur de refus.
- **Politique par defaut permissive** : seules les gardes de position et de
  qualite des donnees sont actives. Les campagnes G5/G9 devront calibrer les
  seuils avant tout usage demo/production.

## 9. Recommandation

Passer a la Phase 5 : brancher le catalogue d'instruments, les contraintes
broker et la devise dans le planificateur, puis exposer la politique de
doctrine dans la configuration.

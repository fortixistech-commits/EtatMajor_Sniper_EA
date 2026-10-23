# Rapport - Phase 5 : planificateur, instrument et politique (G5)

**Projet :** ETAT-MAJOR SNIPER EA - **Date :** 2026-10-22
**Branche :** `fix/phase-c-corrections`
**Porte visee :** G5
**Verdict :** **PASS**, avec limites documentees.

---

## 1. Objectif

Brancher le catalogue d'instruments et les contraintes broker dans le
planificateur, valoriser le risque dans la devise du compte, et exposer la
politique de doctrine dans la configuration validee.

## 2. Etat initial et defauts identifies

| Defaut | Risque | Correction |
| --- | --- | --- |
| Planificateur limite aux valeurs par defaut | quantite non conforme au broker | contraintes `InstrumentSpec` / `BrokerSymbolSpec` |
| Aucun controle du pas/min/max broker | ordre refuse ou surdimensionne | pas, minimum et maximum resolus et appliques |
| Risque calcule en distance de prix brute | risque faux hors devise de cotation | valorisation `tick_value` / `contract_size` |
| Conversion de devise implicite | risque silencieusement faux | refus explicite sans conversion disponible |
| Prix non arrondis au tick | prix non tradable | arrondi a `price_precision` |
| Politique de doctrine non configurable | seuils codes en dur | section `[sniper]` validee et hashee |
| Aucune fabrique runtime | cablage manuel et divergent | `build_planner`, `build_policy`, `build_engine` |

## 3. Fichiers modifies

| Fichier | Nature |
| --- | --- |
| `src/etatmajor/sniper/planner.py` | contraintes instrument/broker, valorisation, arrondis |
| `src/etatmajor/sniper/engine.py` | injection instrument/broker/devise vers le planificateur |
| `src/etatmajor/sniper/settings.py` | **nouveau** - fabriques depuis `SniperConfig` |
| `src/etatmajor/core/config.py` | `SniperConfig`, section `[sniper]`, fingerprint |
| `configs/simulation.toml` | section `[sniper]` explicite |
| `tests/unit/test_sniper_g5.py` | **nouveau** - 14 tests |
| `artifacts/example_report.json` | regenere apres changement de fingerprint |

## 4. Decisions

### 4.1 Ordre de priorite des contraintes

Le planificateur resout les contraintes dans cet ordre :

1. valeurs du `MissionPlanner` (compatibilite et tests historiques) ;
2. `InstrumentSpec` s'il est fourni (pas, minimum, maximum, precision) ;
3. `BrokerSymbolSpec` s'il est fourni (le broker impose ses limites).

Un mapping broker qui ne reference pas l'instrument fourni est refuse.

### 4.2 Valorisation du risque

Si `tick_value` et `contract_size` sont disponibles, la valeur d'un mouvement
de prix unitaire pour une unite d'instrument vaut :

```text
tick_value / (tick_size * contract_size)
```

Le risque planifie est alors exprime dans `tick_value_currency`. Si cette
devise differe de la devise du compte, le plan est refuse : aucune conversion
FX n'est inventee. Sans `tick_value` exploitable, le calcul reste en distance
de prix, mais uniquement si la devise de cotation egale la devise du compte.

Les prix d'entree, de stop et de cible sont arrondis a `price_precision`.
La quantite est arrondie vers le bas au pas, puis bornee au maximum.

### 4.3 Configuration

`[sniper]` expose le risque, le multiple R, les contraintes de volume, les
durees, les seuils de doctrine, le facteur de timeframe superieur et la
qualite minimale des donnees. La section est validee au chargement et incluse
dans le fingerprint de configuration.

`settings.py` fournit les fabriques `build_policy`, `build_planner` et
`build_engine` : une seule source de verite, testee, sans duplication de
valeurs par defaut.

## 5. Resultats

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\test_sniper_g5.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

- Tests G5 : **14 passes**.
- Suite complete : **508 passes, 0 echec** (local, Windows, Python 3.14.0).
- Artefact regenere : fingerprint `abe592c1033ff57c` ; acceptance verte.

## 6. Criteres d'acceptation

| Critere | Etat | Preuve |
| --- | --- | --- |
| Contraintes broker prioritaires | PASS | `test_broker_constraints_override_planner_defaults` |
| Quantite bornee au maximum | PASS | `test_max_quantity_is_clamped_and_aligned` |
| Risque valorise par tick/contrat | PASS | `test_tick_value_and_contract_size_value_the_risk` |
| Devise incompatible refusee | PASS | tests de conversion dedies |
| Mapping broker incoherent refuse | PASS | `test_broker_mapping_must_match_instrument` |
| Prix arrondis a la precision | PASS | `test_prices_are_rounded_to_instrument_precision` |
| Minimum broker respecte | PASS | `test_quantity_below_broker_minimum_is_refused` |
| Comportement historique preserve | PASS | `test_without_instrument_behaviour_is_unchanged` |
| Configuration validee et hashee | PASS | trois tests de configuration |
| Fabriques runtime coherentes | PASS | `test_settings_build_an_engine_with_the_configured_limits` |

## 7. Limites

1. La CLI expose encore uniquement la strategie de demonstration : aucun
   parcours CLI ne selectionne le Sniper Engine avec catalogue.
2. Les couts estimes restent par unite d'instrument ; ils ne sont pas encore
   convertis ni inclus dans la décision de risque.
3. Aucune conversion FX n'est implementee ; l'absence de donnee est refusee.
4. `max_open_positions` reste raisonne sur une position nettee par instrument.
5. Les seuils de doctrine restent non calibres statistiquement.
6. Le planificateur n'arrondit pas le risque a la devise (pas de sous-unite).

## 8. Risques residuels

- **Devise du compte implicite** : sans `account_currency`, la devise de
  cotation ou de valeur du tick est supposee etre celle du compte. Les
  appelants doivent la fournir des qu'elle est connue.
- **Couts hors risque** : un plan peut respecter le risque demande hors frais ;
  le RiskGovernor et la Phase 6 devront integrer les couts.
- **Pas de conversion FX** : les instruments dont la valeur n'est pas
  directement dans la devise du compte sont refuses, ce qui peut bloquer des
  paires legitimes tant que le convertisseur n'existe pas.

## 9. Recommandation

Passer a la Phase 6 : execution simulee et reconciliation, en verifiant que
les contraintes d'instrument resolues ici sont respectees par le broker
simule et que les couts sont correctement comptabilises.

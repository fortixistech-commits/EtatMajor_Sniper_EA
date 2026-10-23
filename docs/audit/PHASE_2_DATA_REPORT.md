# Rapport - Phase 2 : catalogue d'instruments et provenance des donnees

**Projet :** ETAT-MAJOR SNIPER EA - **Date :** 2026-10-22
**Branche :** `fix/phase-c-corrections`
**Porte visee :** G2
**Verdict :** **PASS**, avec limites documentees.

---

## 1. Objectif et perimetre

Garantir que chaque instrument est decrit par des proprietes explicites et
versionnees, et que chaque dataset est rattache a une provenance verifiable.

Hors perimetre de cette phase : ingestion MT5 en direct, calendrier de
sessions, ajustements corporate actions, branchement du catalogue dans le
calcul de taille (Phase 5).

## 2. Etat initial

- `src/etatmajor/data/` ne contenait qu'un chargeur CSV et un rapport de
  qualite minimal (doublons, ordre, gaps, prix non positifs).
- Aucun catalogue d'instruments : les quantites et tailles de tick
  provenaient de la configuration, sans validation par instrument.
- Aucune provenance : le dataset exposait un chemin et un SHA-256, sans
  source, fuseau, granularite ni version.
- Les barres OHLC incoherentes ajoutaient une erreur mais n'etaient pas
  comptees ni rejetees de facon homogene.
- Aucun controle d'alignement des prix au tick de l'instrument.

## 3. Fichiers crees ou modifies

| Fichier | Nature |
| --- | --- |
| `src/etatmajor/data/instruments.py` | **nouveau** - `InstrumentSpec`, `BrokerSymbolSpec`, `InstrumentCatalog`, `UnknownInstrumentError` |
| `src/etatmajor/data/provenance.py` | **nouveau** - `DataProvenance`, chargement TOML, validation |
| `src/etatmajor/data/loader.py` | dataset enrichi, checksum de provenance, compteurs qualite, alignement tick |
| `src/etatmajor/data/validation.py` | compteurs de defauts et couverture des donnees |
| `src/etatmajor/cli.py` | options `--instrument-catalog`, `--broker-id`, `--provenance` |
| `configs/instruments.toml` | **nouveau** - catalogue de reference du laboratoire (v1.0.0) |
| `configs/data_provenance.sample.toml` | **nouveau** - provenance du jeu synthetique |
| `tests/unit/test_instruments.py` | **nouveau** - 17 tests |
| `tests/unit/test_provenance.py` | **nouveau** - 10 tests |
| `tests/unit/test_data_quality_phase2.py` | **nouveau** - 12 tests |
| `tests/integration/test_data_provenance_integration.py` | **nouveau** - 2 tests |

## 4. Decisions techniques

### 4.1 Le catalogue est la seule source de verite

`InstrumentCatalog.require(symbol)` leve `UnknownInstrumentError` si le
symbole est absent. Aucune valeur par defaut n'est inventee : un instrument
inconnu ne peut pas etre simule silencieusement.

### 4.2 Proprietes de l'instrument et contraintes du broker sont separees

- `InstrumentSpec` : classe d'actif, devises, precision, tick, valeur du tick,
  taille de contrat, quantites minimale / pas / maximale.
- `BrokerSymbolSpec` : nom du symbole chez le broker, `instrument_id`,
  contraintes de volume propres au broker.

Un broker qui reference un instrument absent est refuse au chargement.

### 4.3 Unites explicites

Les quantites sont en **unites d'instrument**, pas en lots. `tick_value` est
la valeur d'un tick pour un lot (`contract_size` unites), dans
`tick_value_currency`. Ce choix est documente dans l'en-tete du catalogue.

### 4.4 Provenance verifiable, pas declaree

La provenance contient source, URI, date de recuperation, fuseau,
granularite, version, ajustements, indicateur synthetique et limitations.
Si aucun checksum n'est fourni, le chargeur enregistre le SHA-256 **mesure**
du fichier. Si un checksum est fourni et differe, le chargement echoue.

Aucune conversion de fuseau n'est appliquee : les timestamps sont deja
normalises en UTC, et la provenance declare le fuseau de la source.

### 4.5 Politique erreur / avertissement

| Defaut | Politique |
| --- | --- |
| OHLC incoherent, prix <= 0, volume < 0, valeur non numerique | erreur, ligne rejetee |
| Doublon ou timestamp desordonne | erreur, ligne rejetee |
| Checksum de provenance different | erreur |
| Gaps, timestamps non alignes, prix hors tick | avertissement, compteur visible |
| Granularite de provenance differente du timeframe | avertissement |

Les avertissements ne bloquent pas un replay mais sont presents dans
`dataset.quality` et donc dans le rapport.

## 5. Commandes executees

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m etatmajor.cli validate `
  --data data\sample_eurusd_1m.csv `
  --config configs\simulation.toml `
  --instrument-catalog configs\instruments.toml `
  --provenance configs\data_provenance.sample.toml
```

## 6. Resultats reels

- Suite complete : **438 tests passes, 0 echec**.
- Nouveaux cas explicites de la phase : **41**.
- Tests d'architecture supplementaires generes par les deux nouveaux
  modules : 6.
- Le rapport de replay expose desormais
  `dataset.instrument`, `dataset.catalog_version`, `dataset.provenance` et
  les compteurs de qualite etendus.
- L'artefact `artifacts/example_report.json` a ete regenere
  (empreinte `0cec648541908813`).

## 7. CI

Non executee : aucun identifiant GitHub utilisable dans la session. Les
resultats ci-dessus sont **locaux** (Windows, Python 3.14.0).

## 8. Limites restantes

1. Les valeurs de `configs/instruments.toml` sont des references de
   laboratoire, pas des specifications broker verifiees.
2. Le catalogue n'est pas encore utilise par le calcul de taille de position
   (Phase 5) ni par le broker simule.
3. Les sessions, jours feries et coupures de week-end ne sont pas modelises :
   les gaps correspondants sont comptes comme des barres manquantes.
4. Aucun ajustement de donnees (split, dividende) n'est applique ; le champ
   `adjustments` est declaratif.
5. Le fuseau est declare et valide syntaxiquement, pas converti.
6. Les ticks reels et les donnees MT5 ne sont pas encore ingeres (Phase 10).

## 9. Criteres d'acceptation

| Critere | Etat | Preuve |
| --- | --- | --- |
| Unites coherentes | PASS | catalogue + tests `test_eurusd_properties_are_explicit` |
| Instrument inconnu sans parametres arbitraires | PASS | `test_an_unknown_instrument_is_refused_without_defaults` |
| Donnees invalides detectees | PASS | 12 tests de qualite |
| Donnees identifiables et reproductibles | PASS | SHA-256, provenance, version catalogue, empreinte dataset |
| Defauts de qualite visibles dans les rapports | PASS | `dataset.quality` dans le rapport |
| Proprietes instrument / broker separees | PASS | `InstrumentSpec` vs `BrokerSymbolSpec` |
| Sources, date, incertitudes documentees | PASS | provenance + en-tete du catalogue |

## 10. Risques residuels

- **Risque de specification** : utiliser les valeurs du catalogue pour un
  compte reel sans verification broker produirait un risque mal calibre.
  Mitigation : statut de reference explicite, Phase 5 et Phase 14.
- **Risque de couverture** : les gaps de week-end gonflent
  `missing_bars`. Mitigation : `gap_count` et `coverage_ratio` permettent de
  distinguer un trou isole d'une fermeture reguliere.

## 11. Recommandation

Passer a la Phase 3 (Market Intelligence et detecteur de regimes). Le
catalogue et la provenance sont prets a etre consommes par le planificateur
de mission en Phase 5 ; aucun ordre reel n'est possible.

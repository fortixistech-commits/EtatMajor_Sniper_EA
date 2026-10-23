# Rapport - Phase 6 : execution simulee et reconciliation (G6)

**Projet :** ETAT-MAJOR SNIPER EA - **Date :** 2026-10-22
**Branche :** `fix/phase-c-corrections`
**Porte visee :** G6
**Verdict :** **PASS**, avec limites documentees.

---

## 1. Objectif

Verifier que l'execution simulee respecte les contraintes de l'instrument et
du broker, que les couts sont comptabilises une seule fois, et que l'etat
final du portefeuille peut etre **reconcilie** avec les ordres et les fills.

## 2. Etat initial et defauts identifies

| Defaut | Risque | Correction |
| --- | --- | --- |
| Broker limite a `ExecutionConfig` | contraintes Phase 5 ignorees | `InstrumentSpec` / `BrokerSymbolSpec` injectes |
| Commission basee sur `lot_size` global | cout faux si contrat different | `contract_size` de l'instrument prioritaire |
| Prix non contraints au tick | prix non tradable accepte | alignement tick exige pour limite/stop |
| Prix de fill arrondi a 10 decimales | prix hors precision instrument | arrondi a `price_precision` |
| Aucune reconciliation ordres/fills/portefeuille | erreur comptable invisible | module dedie, echec bloquant |
| Aucun evenement de reconciliation | audit incomplet | evenement `RECONCILIATION` dans le journal |
| CLI perdait la configuration Sniper en override | seuils silencieusement remplaces | `sniper=config.sniper` preserve |

## 3. Fichiers modifies

| Fichier | Nature |
| --- | --- |
| `src/etatmajor/execution/broker.py` | contraintes instrument/broker, tick, contrat, arrondis |
| `src/etatmajor/execution/reconciliation.py` | **nouveau** - reconciliation et PnL recalcule |
| `src/etatmajor/replay/engine.py` | injection instrument, reconciliation bloquante |
| `src/etatmajor/reporting/report.py` | section `reconciliation`, resume, schema 1.1 |
| `src/etatmajor/core/types.py` | evenement `RECONCILIATION` |
| `src/etatmajor/cli.py` | catalogue vers le broker, conservation de `[sniper]` |
| `tests/unit/test_execution_g6.py` | **nouveau** - 17 tests |
| `artifacts/example_report.json` / `example_journal.jsonl` | regeneres |

## 4. Decisions

### 4.1 Contraintes effectives du broker

Ordre de priorite :

1. `ExecutionConfig` (compatibilite historique) ;
2. `InstrumentSpec` (pas, minimum, maximum, precision, contrat) ;
3. `BrokerSymbolSpec` (le mapping broker impose ses limites).

Le broker refuse un mapping broker qui ne reference pas l'instrument fourni.
Les ordres limite/stop doivent etre alignes au tick de l'instrument.

### 4.2 Couts et prix

La commission par lot utilise `contract_size` lorsqu'il est disponible, sinon
`lot_size` de la configuration. Les prix de fill sont arrondis a la precision
de l'instrument. Le risque planifie reste hors couts : la reconciliation
verifie la comptabilite, elle ne transforme pas les frais en risque.

### 4.3 Reconciliation

`reconcile()` controle :

- unicite des identifiants d'ordre ;
- existence de l'ordre pour chaque fill, coherence symbole/sens/volume ;
- volume rempli, statut, quantite remplie et prix moyen de chaque ordre ;
- position nette par symbole = somme signee des fills ;
- frais du portefeuille = somme des commissions ;
- PnL realise recalcule par netting = PnL du portefeuille ;
- invariants `cash = capital + realise - frais` et `equity = cash + latent`.

Toute divergence produit une issue typée et **bloque la publication du
rapport** (`ExecutionError`). Le rapport contient la section `reconciliation`
et le journal l'evenement `RECONCILIATION`.

## 5. Resultats

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\test_execution_g6.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

- Tests G6 : **17 passes**.
- Suite complete : **528 passes, 0 echec** (local, Windows, Python 3.14.0).
- Artefact regenere : fingerprint `3f7621a5725a1196`.
- Replay CLI avec catalogue : reconciliation OK, aucun rejet broker sur le
  scenario de reference.

## 6. Criteres d'acceptation

| Critere | Etat | Preuve |
| --- | --- | --- |
| Contraintes broker prioritaires | PASS | `test_broker_uses_broker_symbol_constraints` |
| Contraintes instrument sans mapping | PASS | `test_instrument_constraints_are_used_without_a_broker_mapping` |
| Commission par contrat | PASS | `test_commission_uses_the_instrument_contract_size` |
| Prix limite aligne au tick | PASS | `test_unaligned_limit_prices_are_rejected` |
| Prix de fill arrondi | PASS | `test_fill_prices_are_rounded_to_the_instrument_precision` |
| Mapping incoherent refuse | PASS | `test_broker_refuses_a_mismatched_instrument_mapping` |
| Reconciliation nominale | PASS | `test_a_clean_record_reconciles` |
| Fill orphelin, position, frais, PnL, doublons | PASS | six tests de divergence |
| Rapport et journal exposes | PASS | `test_the_replay_engine_publishes_a_reconciliation_section` |
| Echec bloquant | PASS | `test_the_replay_engine_refuses_an_unreconciled_execution` |
| Contraintes propagees par le moteur | PASS | `test_the_replay_engine_wires_instrument_constraints_into_the_broker` |

## 7. Limites

1. Pas de fills partiels : chaque ordre est rempli en une fois ou pas du tout.
2. Pas de duree de vie, de stop-loss/take-profit attaches a l'ordre, ni de
   modification d'ordre en cours de vie.
3. La reconciliation compare le broker interne au portefeuille interne ; elle
   ne remplace pas un rapprochement avec un releve broker externe.
4. Les commissions sont supposees libellees dans la devise du compte ; aucune
   conversion FX n'est appliquee.
5. Le risque du RiskGovernor n'integre toujours pas les couts.
6. L'arrondi au tick peut modifier le prix de fill par rapport a l'ancien
   arrondi a 10 decimales ; les artefacts ont ete regeneres.

## 8. Risques residuels

- **Reconciliation circulaire** : les deux sources sont internes. Un bug
  commun aux deux composants ne serait pas detecte ; les invariants
  independants (PnL recalcule, cash) reduisent ce risque sans l'annuler.
- **Couts hors risque** : un plan peut rester dans la limite demandee hors
  frais. La Phase 9 devra mesurer l'impact des couts.
- **Ordres rejetes sans position** : une strategie peut continuer a envoyer
  des sorties apres un rejet d'entree, comme le montre le test de propagation.
  Le compteur de refus devra etre borne en Phase 7.

## 9. Recommandation

Passer a la Phase 7 : replay de bout en bout et scenarios de challenge, en
verifiant que les rejets, les sorties sans position et les transitions de
challenge restent coherents avec la reconciliation.

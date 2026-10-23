# Rapport - Phase 7 : replay de bout en bout, challenge et scenarios (G7)

**Projet :** ETAT-MAJOR SNIPER EA - **Date :** 2026-10-22
**Branche :** `fix/phase-c-corrections`
**Porte visee :** G7
**Verdict :** **PASS local**, avec limites documentees (aucune CI distante).

---

## 1. Objectif

Verifier que le pipeline complet - donnees, intelligence de marche, strategie
Sniper, planification, RiskGovernor, execution simulee, comptabilite,
reconciliation, challenge, rapport - fonctionne de bout en bout, reste
reproductible et ne cache jamais un scenario defavorable.

## 2. Etat initial et defauts identifies

| Defaut | Risque | Correction |
| --- | --- | --- |
| CLI sans selection de strategie | le Sniper n'etait pas rejouable par la CLI | option `--strategy {demo,sniper}` (defaut `demo`) |
| Qualite des donnees non transmise au Sniper | donnees degradees acceptees silencieusement | `build_engine(..., data_quality=...)`, `dataset.quality` cable |
| `DataQualityAssessment.from_report` n'acceptait qu'un objet | dict de qualite interprete comme 0 barre manquante | support des mappings et des compteurs |
| `steps_completed` valait `step_index` apres validation finale | etape validee mais compteur faux | `len(profile.steps)` si le profil est passe |
| Heure de reset non validee | `24`, `1.5`, `True` acceptes | entier strict dans `[0, 23]`, bool refuse |
| Aucune trace des transitions de challenge | verdict non auditable | evenements `CHALLENGE_EVENT`, `CHALLENGE_FINALIZED` |
| `REPLAY_FINISHED` ecrit avant la finalisation du challenge | evenement final incoherent | ordre de fin de replay refactorise |
| `Portfolio.snapshot()` allouait a chaque bougie | cout inutile sur les longues series | instantane immuable partage tant que le portefeuille est a plat |
| Aucun scenario d'integration Phase 7 | couverture incomplete | 12 tests d'integration + 4 tests unitaires cibles |

## 3. Fichiers modifies

| Fichier | Nature |
| --- | --- |
| `src/etatmajor/cli.py` | `--strategy`, cablage `SniperStrategy`, qualite des donnees |
| `src/etatmajor/sniper/settings.py` | `build_engine` accepte `data_quality` |
| `src/etatmajor/sniper/market_intelligence.py` | rapport de qualite objet ou mapping |
| `src/etatmajor/challenge/engine.py` | validation reset, transitions, `steps_completed`, `drain_events` |
| `src/etatmajor/replay/engine.py` | fin de replay ordonnee, journal des transitions |
| `src/etatmajor/execution/accounting.py` | cache de l'instantane a plat |
| `src/etatmajor/core/types.py` | `CHALLENGE_EVENT`, `CHALLENGE_FINALIZED` |
| `src/etatmajor/reporting/report.py` | compteurs de strategie, schema 1.2, phase 7 |
| `scripts/benchmark_replay.py` | profils 240 / 5 000 / 20 000 / 100 000 |
| `tests/integration/test_phase7_pipeline.py` | **nouveau** - 12 tests |
| `tests/unit/test_phase7_corrections.py` | **nouveau** - 4 tests |
| `docs/audit/evidence/benchmark.json` | preuve de performance regeneree |
| `artifacts/example_report.json` / `example_journal.jsonl` | regeneres |

## 4. Decisions

### 4.1 Ordre de fin de replay

La sequence est desormais explicite et stable :

1. cloture des ordres et positions selon la politique de fin de replay ;
2. reconciliation bloquante ;
3. `on_stop` de la strategie ;
4. observation post-liquidation, finalisation du challenge et evenements ;
5. `CHALLENGE_FINALIZED` ;
6. `REPLAY_FINISHED` en dernier evenement.

Le verdict porte donc sur l'equity **apres** liquidation, et le journal se
termine toujours par l'evenement de fin de replay.

### 4.2 Tracabilite des transitions

Le challenge n'emet un evenement que lorsqu'un fait nouveau se produit :
echec terminal, validation d'etape, profil passe. Les observations
dupliquees ou contradictoires ne creent aucun evenement. Chaque evenement
est horodate en temps simule.

### 4.3 Performance

L'instantane d'un portefeuille a plat est immuable et partage ; tout fill
invalide le cache. Le cout par bougie du moteur de replay devient lineaire
sur les profils mesures.

Le Sniper Engine n'est pas inclus dans le profil 100 000 bougies : son
Market Intelligence recalcule les indicateurs sur tout l'historique visible
a chaque bougie, ce qui reste quadratique. Cette limite est explicite dans
le script de benchmark et devra etre levee avant un replay Sniper de
campagne.

## 5. Resultats

```powershell
.\.venv\Scripts\python.exe -m pytest tests\integration\test_phase7_pipeline.py -q
.\.venv\Scripts\python.exe -m pytest tests\unit\test_phase7_corrections.py -q
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\benchmark_replay.py --output docs\audit\evidence
```

- Tests Phase 7 : **16 passes** (12 integration + 4 unitaires).
- Suite complete : **544 passes, 0 echec** (local, Windows, Python 3.14.0).
- Artefact regenere : fingerprint `2d3f11af198caf16` (phase 7, schema 1.2).
  Il est remplace en Phase 8 par le fingerprint `4d0f37dc0db9ec09`
  (schema 1.3, section `observability`).
- Benchmark demo : 240 / 5 000 / 20 000 / 100 000 bougies, environ
  35 000 / 91 000 / 94 000 / 99 000 bougies/s.
- Sniper sur 5 000 bougies : environ 43 bougies/s (limite connue, non
  presentee comme un resultat de campagne).

## 6. Criteres d'acceptation

| Critere | Etat | Preuve |
| --- | --- | --- |
| Pipeline Sniper -> risque -> execution | PASS | `test_the_sniper_pipeline_can_engage_through_risk_and_execution` |
| Abstention sans transaction | PASS | `test_an_abstaining_series_never_produces_a_transaction` |
| Donnees degradees refusees | PASS | `test_degraded_data_is_refused_by_the_sniper_pipeline` |
| CLI Sniper de bout en bout | PASS | `test_the_cli_can_run_the_sniper_strategy` |
| Trajectoire gagnante -> PASSED | PASS | `test_a_winning_trajectory_passes_a_verified_profile_and_is_journaled` |
| Trajectoire perdante -> FAILED terminal | PASS | `test_a_losing_trajectory_fails_the_profile_terminally` |
| Progression multi-etapes | PASS | `test_a_multi_step_profile_records_each_advance` |
| Evenements non dupliques | PASS | `test_repeated_observations_do_not_duplicate_the_verdict_events` |
| Kill switch apres redemarrage | PASS | `test_the_kill_switch_survives_a_restart_and_blocks_new_risk` |
| Rearmement explicite | PASS | `test_a_kill_switch_can_only_be_rearmed_with_a_reason` |
| Reproductibilite rapport + journal | PASS | `test_two_identical_runs_produce_identical_reports_and_journals` |
| Concordance compte / challenge / reconciliation | PASS | `test_account_challenge_and_reconciliation_metrics_agree` |
| Reset horaire valide | PASS | `test_the_reset_hour_is_validated` |
| Qualite objet ou mapping | PASS | `test_quality_reports_accept_both_objects_and_mappings` |
| Instantane a plat partage puis invalide | PASS | `test_a_flat_snapshot_is_shared_until_a_fill` |

## 7. Limites

1. **Sniper quadratique** : le Market Intelligence recalcule son historique
   complet a chaque bougie ; un replay Sniper de 100 000 bougies n'est pas
   realiste en l'etat.
2. **Challenge en memoire** : l'etat du challenge ne survit pas a un
   redemarrage ; seul le kill switch est persistant.
3. **Kill switch** : pas de verrou inter-processus, rearmement non signe.
4. **Profil The5ers** : toujours `DRAFT` ; les regles V1-V8 et les frais V4
   ne sont pas verifies contractuellement.
5. **Execution** : pas de fills partiels, pas de TIF, pas de SL/TP attaches
   ni de modification d'ordre.
6. **Couts** : toujours hors du risque planifie par le RiskGovernor.
7. **Donnees** : sessions UTC simplifiees, un seul timeframe superieur.

## 8. Risques residuels

- Une campagne Sniper longue reste lente : ce n'est pas un risque de
  correction mais un risque d'exploitation.
- Un redemarrage pendant une campagne perd l'etat du challenge ; le kill
  switch reste engage, ce qui est fail-closed mais ne permet pas de reprendre.
- Aucune preuve CI distante : les 544 tests sont locaux.

## 9. Conclusion

La porte G7 est franchie localement : le pipeline complet est rejouable,
les scenarios defavorables sont visibles, le challenge est audite et les
metriques concordent. Les limites ci-dessus doivent rester affichees dans
toute presentation des resultats.

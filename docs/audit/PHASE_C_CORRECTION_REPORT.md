# Rapport - Corrections de la Phase C (C1 a C7)

**Projet :** ETAT-MAJOR SNIPER EA - **Date :** 2026-10-22
**Branche :** `fix/phase-c-corrections` (base : `feat/phase-d-sniper-engine`, `4f56f19`)
**Decision proposee :** **PASS** pour les corrections C1-C7, avec limites
explicitement documentees. Aucune fusion, aucun ordre reel.

> Les corrections portent sur des defauts de surete du Challenge Engine, du
> RiskGovernor et du kill switch. Elles ne changent pas la doctrine de
> trading et n'ajoutent aucune revendication de conformite a un profil prop
> firm non verifie.

---

## 1. Resultat

| Correction | Objet | Verdict | Preuve principale |
| --- | --- | --- | --- |
| C1 | determinisme et idempotence du Challenge Engine | **PASS** | `test_evaluate_does_not_mutate_the_challenge_state`, `test_two_targets_crossed_in_one_observation_validate_only_one_step`, `test_a_duplicate_observation_does_not_advance_another_step`, `test_stale_and_conflicting_observations_are_ignored` |
| C2 | echec terminal et suivi des pertes maximales | **PASS** | `test_a_daily_loss_breach_is_terminal_even_after_recovery`, `test_a_daily_reset_does_not_clear_a_terminal_failure`, `test_a_total_loss_breach_is_terminal`, `test_balance_equity_and_floating_losses_are_distinguished`, `test_max_losses_are_updated_at_every_observation` |
| C3 | verdict apres liquidation de fin de replay | **PASS** | `test_the_verdict_uses_the_post_liquidation_equity`, `test_mark_to_market_policy_does_not_realise_the_exit` |
| C4 | exposition agregee et refus des donnees invalides | **PASS** | 11 tests dans `tests/unit/test_risk_governor_corrections.py` |
| C5 | kill switch fail-closed et rearmement trace | **PASS** | 10 tests dans `tests/unit/test_killswitch_corrections.py` |
| C6 | profil The5ers coherent et generique | **PASS** | `test_the_reference_document_points_to_the_existing_toml_profile`, `test_the_shipped_profile_is_internally_consistent`, `test_a_second_prop_firm_profile_is_supported_without_code_change` |
| C7 | compatibilite Windows des preuves | **PASS** | `scripts/benchmark_replay.py` execute sous Windows, RSS mesure |

**Suite complete : 391 tests passes, 0 echec** (340 avant les corrections, +51).

Commandes executees :

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\benchmark_replay.py --output docs\audit\evidence
```

---

## 2. Corrections apportees

### 2.1 C1 - Challenge Engine deterministe

- Separation stricte entre `observe()` (accumule un etat de compte horodate)
  et `evaluate()` (lecture pure, sans mutation).
- Une seule etape peut etre validee par observation : deux cibles franchies
  dans la meme bougie ne valident pas deux etapes.
- Les observations dupliquees, en retard ou contradictoires au meme instant
  sont ignorees et comptees (`ignored_observations`) ; elles ne peuvent plus
  rejouer une transition.
- Les jours requis sont suivis par etape, pas globalement.
- Le verdict expose `model_limits` : la simulation ne connait que l'OHLC,
  pas l'ordre intra-bougie des stops et objectifs.

### 2.2 C2 - Echec terminal

- Un franchissement de limite journaliere ou totale cree un `FailureRecord`
  definitif ; aucune recuperation ulterieure ne l'efface.
- `max_daily_loss` et `max_total_loss` sont mis a jour a chaque observation,
  y compris lorsque le compte se retablit ensuite.
- Les lectures solde / equity / flottant sont distinguees ; le verdict
  officiel retient l'interpretation la plus defavorable.
- Le reset journalier remet les compteurs du jour a zero mais conserve
  l'echec et les maxima historiques.

### 2.3 C3 - Verdict post-liquidation

- Apres `_finish_replay()` et `on_stop()`, le moteur observe une derniere
  fois le compte **apres** la politique de fin de replay (liquidation ou
  mark-to-market), puis finalise le challenge.
- L'horodatage de cette observation est strictement posterieur au dernier
  timestamp de bougie (`+1 ns`) : sans cela, l'observation etait rejetee
  comme contradictoire au meme instant (C1) et le verdict gardait l'equity
  d'avant liquidation.
- Resultat mesure : avec un spread de 0,0002 et une position longue encore
  ouverte, le rapport donne `net_pnl = -0,2` et le verdict donne le meme
  `total_pnl`; avant correction le verdict affichait `-0,1`.

### 2.4 C4 - RiskGovernor

- L'exposition brute est projetee **apres** l'operation et comparee a
  `max_leverage x equity`; elle inclut les positions deja ouvertes.
- Une vraie reduction de position reste autorisee meme au-dela du plafond
  (elle diminue le risque).
- Un retournement de position n'est pas traite comme une reduction : s'il
  depasse la limite, il est refuse. Cela ferme le contournement du plafond
  d'exposition et de `max_open_positions`.
- Les quantites, prix et stops non finis, nuls ou negatifs sont refuses
  avant tout calcul.
- Le kill switch est verifie en premier et reste fail-closed.

### 2.5 C5 - Kill switch

- Schema JSON strict : `engaged` obligatoire, types verifies, cles inconnues
  refusees. Un fichier existant mais invalide engage le switch.
- Fichier obligatoire absent, chemin illisible ou repertoire a la place du
  fichier : engagement immediat (`state_error = True`).
- Ecriture atomique (`temp` + `fsync` + `os.replace`). Un echec d'ecriture
  leve `ConfigurationError` et laisse l'etatengage en memoire.
- `reset()` exige un fichier persistant et un motif non vide ; l'horodatage,
  le motif et l'operateur sont conserves dans le fichier.

### 2.6 C6 - Profils

- Le profil The5ers reste `DRAFT`, avec `verified_by` honnete et V4 (frais)
  documente comme non tranche.
- Validation de coherence pourcentage / montant sur les limites.
- La reference documentaire pointe vers le TOML existant (plus de `.yaml`).
- Un second profil est accepte sans modification de code (test dedie).

### 2.7 C7 - Preuves Windows

- `scripts/benchmark_replay.py` ne depend plus du module Unix `resource`.
- Le RSS Windows est lu via `psapi.GetProcessMemoryInfo` avec des types
  `ctypes` corrects (le handle de processus etait tronque en `int`).
- Une erreur de concatenation dans l'affichage du benchmark a ete corrigee
  (`SyntaxWarning` en Python 3.14).

Mesure locale (Windows, Python 3.14.0) :

| Bougies | Replay | Debit | Memoire (RSS) |
| --- | --- | --- | --- |
| 240 | 0,007 s | ~35 000 bars/s | 23,2 MB |
| 5 000 | 0,060 s | ~84 000 bars/s | 24,4 MB |
| 10 000 | 0,117 s | ~85 000 bars/s | 26,4 MB |
| 20 000 | 0,234 s | ~85 000 bars/s | 29,6 MB |

Preuve complete : `docs/audit/evidence/benchmark.json`.

---

## 3. Fichiers modifies

| Fichier | Nature |
| --- | --- |
| `src/etatmajor/challenge/engine.py` | observe/evaluate, echec terminal, maxima, finalize, limites de modele |
| `src/etatmajor/challenge/profile.py` | validation pourcentage / montant |
| `src/etatmajor/risk/governor.py` | exposition agregee, reduction pure, validation d'entree |
| `src/etatmajor/risk/killswitch.py` | schema strict, fail-closed, persistance atomique, reset trace |
| `src/etatmajor/core/config.py` | `kill_switch_required` et validation associee |
| `src/etatmajor/replay/engine.py` | observation post-liquidation et horodatage strictement croissant |
| `configs/prop_firms/the5ers_high_stakes_new_2500.draft.toml` | statut DRAFT honnete, V4 corrige |
| `docs/propfirm/THE5ERS_REFERENCE.md` | chemin TOML, V4 |
| `scripts/benchmark_replay.py` | portabilite Windows, RSS |
| `artifacts/example_report.json` | regeneré (empreinte `4d18a249e9c16b54`) |
| `tests/unit/test_challenge_corrections.py` | **nouveau** - 15 tests |
| `tests/unit/test_risk_governor_corrections.py` | **nouveau** - 20 cas (parametres inclus) |
| `tests/unit/test_killswitch_corrections.py` | **nouveau** - 14 tests |
| `tests/integration/test_challenge_finalization.py` | **nouveau** - 2 tests |

---

## 4. Limites residuelles (assumees)

1. **Modele intra-bougie** : l'ordre des stops et objectifs dans une meme
   bougie reste inconnu ; la simulation ne peut pas certifier un tick
   d'execution. Le verdict le declare via `model_limits`.
2. **Kill switch mono-ecrivain** : le fichier n'est pas verrouille entre
   processus. L'exploitation doit garantir un seul ecrivain.
3. **Horodatages de rearmement** : `reset()` fait confiance au timestamp et
   a l'operateur fournis par l'appelant ; aucune signature cryptographique.
4. **Profil The5ers** : toujours `DRAFT`. V1-V8 ne sont pas tranchees et les
   frais (V4) ne sont pas deduits. Aucune conformite officielle n'est
   declaree.
5. **Performance au-dela de 20 000 bougies** : non re-mesuree apres les
   corrections ; la mesure 5k-20k est quasi lineaire (~11,7 us/bougie).
6. **Validation de coherence des profils** : seules les limites journaliere
   et totale sont controlees ; les autres champs restent valides par type.

---

## 5. Blocages

- **Push / PR** : l'environnement ne dispose pas d'identifiants GitHub
  utilisables dans cette session. Les branches restent locales ; aucune
  fusion n'est effectuee.
- **CI distante** : non executee. Le resultat de 391 tests est local
  (Windows, Python 3.14.0) et ne prouve pas la CI GitHub.

---

## 6. Recommandation

Accepter les corrections C1-C7 pour revue. Avant toute Phase 2 / production :
faire relire le modele intra-bougie et la politique de liquidation par le
chef de projet, puis completer les tests de non-regression sur un jeu de
donnees reel (Phase 3). Le profil The5ers doit rester `DRAFT` tant que les
regles V1-V8 ne sont pas verifiees a la source.

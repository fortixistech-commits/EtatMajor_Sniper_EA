# Etat du projet

**Projet :** ETAT-MAJOR SNIPER EA
**Date :** 2026-10-23
**Phase courante :** Phase 9 (metriques de performance, robustesse, validation et selection) livree, porte G9 ; prochaine etape Phase 10
**Branche de base :** `feat/phase-d-sniper-engine` (`4f56f19`)

---

## 1. Tableau d'avancement

| Phase | Objet | Statut | Preuve |
| --- | --- | --- | --- |
| MISSION 0 | Audit factuel du depot | **Terminee** | `docs/audit/INITIAL_AUDIT.md`, `docs/audit/BACKLOG.md` |
| Phase 0 | Audit et preparation | **Terminee** | `docs/ARCHITECTURE_DECISIONS.md`, `docs/SECURITY.md` |
| Phase 1 | Squelette et contrats | **Terminee** | `src/etatmajor/**`, `pyproject.toml`, `configs/` |
| Phase 2 (ancienne num.) | Replay et execution simulee | **Terminee** | `docs/PHASE2_REPORT.md`, rapport d'exemple versionne |
| Phase C | Challenge Engine, RiskGovernor, kill switch | **Livree** | `docs/audit/PHASE_C_REPORT.md` |
| Phase D | Sniper Engine (doctrine, contexte, planification) | **Livree** | `docs/audit/PHASE_D_REPORT.md`, `tests/unit/test_sniper_doctrine.py` |
| C1-C7 | Corrections de surete de la Phase C | **Livree** | `docs/audit/PHASE_C_CORRECTION_REPORT.md` |
| Phase 2 (feuille de route) | Catalogue d'instruments et provenance des donnees | **Livree (G2)** | `docs/audit/PHASE_2_DATA_REPORT.md`, `configs/instruments.toml` |
| Phase 3 | Market Intelligence et regime detector | **Livree (G3)** | `docs/audit/PHASE_3_MARKET_INTELLIGENCE_REPORT.md` |
| Phase 4 | Sniper Engine et strategie | **Livree (G4)** | `src/etatmajor/sniper/**`, `tests/unit/test_sniper_doctrine.py` |
| Phase 5 | Mission Planner, instrument et politique | **Livree (G5)** | `src/etatmajor/sniper/planner.py` |
| Phase 6 | Execution simulee et reconciliation | **Livree (G6)** | `docs/audit/PHASE_6_EXECUTION_G6_REPORT.md` |
| Phase 7 | Pipeline de bout en bout, challenge et scenarios | **Livree (G7)** | `docs/audit/PHASE_7_PIPELINE_CHALLENGE_REPORT.md` |
| Phase 8 | Cockpit et observabilite | **Livree (G8)** | `docs/audit/PHASE_8_COCKPIT_REPORT.md` |
| Phase 9 | Metriques de performance, robustesse, validation, selection | **Livree (G9)** | `docs/audit/PHASE_9_EVALUATION_REPORT.md` |
| Phases 10-16 | MT5, backtests, demo, production controlee | A faire | - |

## 2. Environnement de reference

| Element | Valeur |
| --- | --- |
| Systeme | Windows (win32) |
| Python | 3.14.0 |
| Environnement | `.venv`, installation `pip install -e ".[dev]"` |
| Moteur de replay | interne `etatmajor.replay` (zero dependance runtime) |
| Tests | pytest, **606 tests au vert** (local) |
| Preuves de performance | `docs/audit/evidence/benchmark.json` |

## 3. Capacites disponibles

* rechargement deterministe de donnees OHLC avec validation et rapport de
  qualite etendu (OHLC, gaps, alignement temporel, alignement au tick) ;
* catalogue d'instruments versionne, sans valeur par defaut pour un symbole
  inconnu, avec mapping broker separe ;
* provenance des donnees verifiable (source, fuseau, granularite, checksum) ;
* horloge simulee, ordre chronologique garanti, absence de fuite temporelle ;
* contrat de strategie (proposition structuree ou abstention explicite) ;
* broker simule (marche, limite, stop) avec spread, slippage, commissions et
  rejets ;
* comptabilite du portefeuille avec invariants testes ;
* autorite de risque avec veto, exposition agregee, stop obligatoire,
  risque par operation et journal d'audit ;
* kill switch persistant fail-closed, rearmement explicite et trace ;
* Challenge Engine multi-profils : etapes, jours profitables, pertes
  journaliere et totales, interpretations solde/equity, verdict explicite ;
* Sniper Engine : regime, contexte, detection de setup, planification,
  abstention motivee ;
* Market Intelligence : ADX/DI, RSI, ATR percentile, structure confirmee,
  alignement multi-timeframe sur bougies cloturees, confiance explicable et
  garde de qualite des donnees ;
* doctrine Sniper qualifiee : une mission a la fois, seuils de confiance,
  structure, timeframe superieur et volatilite activables, plan complet ou
  abstention ;
* planification contrainte par l'instrument et le broker (pas, minimum,
  maximum, precision), risque valorise par tick/contrat, refus explicite de
  toute conversion de devise non disponible ;
* section `[sniper]` validee, hashee et fabriques runtime uniques
  (`build_policy`, `build_planner`, `build_engine`) ;
* broker simule contraint par l'instrument et le mapping broker (pas,
  minimum, maximum, tick, precision, taille de contrat), avec rejet explicite
  des prix non alignes ;
* reconciliation ordres/fills/portefeuille bloquante : volumes, prix moyens,
  position nette, frais, PnL recalcule, invariants de cash et d'equity ;
* politique de fin de replay explicite (liquidation ou mark-to-market) et
  verdict apres liquidation ;
* journal d'evenements JSONL et rapport JSON reproductible ;
* observabilite deterministe : compteurs d'evenements, chronologie, identite
  de session et section `observability` dans le rapport (schema 1.4) ;
* **metriques de performance deterministes : reconstruction de trades par
  netting a cout moyen, profit factor, expectancy, drawdown, echantillonnage
  de courbe d'equity, ventilation par cote et symbole, hypotheses explicites** ;
* **analyse de robustesse : separation chronologique (entrainement/validation/test),
  bootstrap Monte-Carlo deterministe (seed=42), degradation hors echantillon,
  sensibilite aux parametres declaree NOT_AVAILABLE** ;
* **dossier de validation : criteres declares en amont (TOML), verdict
  PASS/FAIL/INCOMPLETE, echec ferme sur critere non mesurable, empreintes
  de criteres et de dossier, non signe, revue humaine requise** ;
* **selection de candidats : classement par verdict, puis percentile 5 bootstrap,
  expectancy, empreinte ; avertissement sur sur-ajustement** ;
* cockpit operateur hors ligne : verification d'integrite rapport/journal,
  rendu HTML autonome, instantane JSON, mode strict et code retour dedie ;
* interface en ligne de commande (validation, replay, rapport, journal,
  profil de challenge, cockpit, **evaluate**, **select**).

## 4. Capacites absentes (par construction)

* aucun envoi d'ordre reel, aucune connexion broker ;
* aucune ingestion de donnees MT5 reelles (Phase 10) ;
* aucune integration MQL5/MT5 (Phase 10/11) ;
* aucune revendication de conformite prop firm : le profil The5ers reste
  `DRAFT` et les regles V1-V8 ne sont pas tranchees.

## 5. Limites connues

* **Modele intra-bougie** : l'ordre des stops et objectifs dans une meme
  bougie est inconnu ; le verdict le declare dans `model_limits`.
* **Kill switch mono-ecrivain** : le fichier d'etat n'est pas verrouille
  entre processus.
* **Rearmement** : l'horodatage et l'operateur sont declares par l'appelant,
  sans signature cryptographique.
* **Frais The5ers (V4)** : non deduits dans le profil DRAFT ; la variante
  apres frais n'est pas simulee.
* **Execution partielle** : chaque ordre est rempli en totalite ou rejete ;
  pas de fills partiels, de duree de vie, de SL/TP attaches ni de
  modification d'ordre.
* **Reconciliation interne** : le rapprochement compare broker et portefeuille
  internes ; il ne remplace pas un releve broker externe.
* **Couts hors risque** : les commissions et le spread ne sont pas integres
  a l'autorisation du RiskGovernor ; seule la comptabilite les verifie.
* **Performance** : la strategie de demonstration reste quasi lineaire
  jusqu'a 100 000 bougies (~99 000 bougies/s en local). Le Sniper reste
  quadratique (Market Intelligence recalcule sur l'historique visible) :
  ~43 bougies/s a 5 000 bougies, replay 100k non exploitable.
* **Cockpit** : vue en lecture seule, non signee ; il detecte une alteration
  accidentelle, pas une falsification deliberee avec re-calcul des empreintes.
* **Selection** : le classement porte sur le meme echantillon de test ; il ne
  remplace pas une validation independante.

## 6. Decisions en attente de validation

| ADR | Decision | Attente |
| --- | --- | --- |
| ADR-001 | moteur interne pour la Phase 2, NautilusTrader reevalue en Phase 4 | arbitrage du chef de projet |
| ADR-002 | execution a l'ouverture de la bougie suivante | arbitrage du chef de projet |
| ADR-003 | quantites en unites instrument, `lot_size` configurable | arbitrage du chef de projet |
| ADR-004 | politique de fin de replay explicite | arbitrage du chef de projet |
| ADR-005 | rapport sans donnee d'environnement | arbitrage du chef de projet |
| ADR-006 | le journal est la source de verite de l'audit | arbitrage du chef de projet |

## 7. Blocages

* **Push / PR** : aucun identifiant GitHub utilisable dans la session. Les
  branches restent locales ; aucune fusion n'est effectuee.
* **CI distante** : non executee. Le resultat de 606 tests est local
  (Windows, Python 3.14.0).
* **Profil The5ers** : verification contractuelle des regles V1-V8
  necessaire avant tout verdict de conformite.

## 8. Prochaines etapes

1. Revue des rapports de phase et des diffs ; aucun merge sans autorisation.
2. Phase 10 : adaptateur MT5 en lecture seule et paper trading.
3. Phases 10-16 : robustesse, MT5, backtests, demo, production controlee.
4. Ne passer aucun ordre reel sans autorisation explicite.
# Rapport - Phase 8 : cockpit et observabilite (G8)

**Projet :** ETAT-MAJOR SNIPER EA - **Date :** 2026-10-22
**Branche :** `fix/phase-c-corrections`
**Porte visee :** G8
**Verdict :** **PASS local**, avec limites documentees (aucune CI distante).

---

## 1. Objectif

Donner a l'operateur une vue **hors ligne, deterministe et lecture seule** sur
une execution deja produite : rapport JSON, journal JSONL, comptes, ordres,
executions, challenge, qualite des donnees et integrite de la chaine d'audit.

La phase ne modifie aucune regle de trading, n'ajoute aucun acces broker et
n'ouvre aucune connexion reseau.

## 2. Decisions de conception

| Decision | Justification |
| --- | --- |
| Cockpit dans `reporting/`, pas dans une nouvelle couche | il ne lit que le rapport et le journal, deja produits par la couche reporting |
| HTML autonome, CSS inline, aucun script | fonctionne sans reseau, sans CDN et sans dependance runtime |
| Aucune horloge murale | deux evidences identiques produisent des sorties identiques |
| Verification stricte par defaut, avertissements separes | une alteration est bloquante, une limite de schema reste visible |
| Code retour `3` sur evidence non conforme | utilisable directement dans un pipeline local |
| Schema de rapport `1.3`, phase `8`, version `0.3.0` | la section `observability` est un ajout de contrat explicite |

## 3. Defauts identifies et corrections

| Defaut | Risque | Correction |
| --- | --- | --- |
| Aucun tableau de bord operateur | rapport JSON illisible pour une revue rapide | commande `cockpit` + HTML autonome + snapshot JSON |
| Aucune vue agregee du journal dans le rapport | comptage et chronologie non verifiables sans script ad hoc | section `observability` (compteurs, bornes, sessions, ordre temporel) |
| Empreinte de rapport privee (`_fingerprint`) | le cockpit ne pouvait pas revalider l'evidence | fonction publique `report_fingerprint` |
| Aucun controle croise rapport/journal | une piece pouvait etre remplacee sans alerte | empreinte, compteurs, session, evenement final, reconciliation, verdict |
| Rendu HTML non protege | injection via symboles, motifs ou identifiants | echappement systematique de toutes les valeurs |
| Pas de sortie machine pour le cockpit | pas d'integration possible dans un controle | `--json` avec snapshot trie et stable |
| Pas de mode strict | un avertissement passait inapercu | `--strict` retourne `3` des qu'un avertissement subsiste |

## 4. Fichiers

| Fichier | Nature |
| --- | --- |
| `src/etatmajor/reporting/cockpit.py` | **nouveau** - chargement, integrity checks, metriques, rendu console/HTML/JSON |
| `src/etatmajor/reporting/report.py` | schema `1.3`, phase `8`, section `observability`, empreinte publique |
| `src/etatmajor/core/errors.py` | `CockpitError` |
| `src/etatmajor/cli.py` | commande `cockpit` (`--report`, `--journal`, `--html`, `--json`, `--title`, `--strict`) |
| `src/etatmajor/__init__.py` | version `0.3.0` |
| `tests/unit/test_cockpit.py` | **nouveau** - 11 tests |
| `tests/integration/test_phase8_cockpit.py` | **nouveau** - 3 tests |
| `tests/acceptance/test_cli.py` | 3 tests d'acceptation du cockpit |
| `artifacts/example_cockpit.html` | **nouveau** - tableau de bord de reference |
| `artifacts/example_cockpit.json` | **nouveau** - snapshot machine de reference |
| `artifacts/example_report.json` / `example_journal.jsonl` | regeneres en schema 1.3 |
| `README.md`, `docs/OPERATIONS.md`, `docs/PROJECT_STATUS.md` | mode d'emploi et etat du projet |

## 5. Controles d'integrite

Le cockpit verifie, dans cet ordre :

1. **Contrat du rapport** : champs obligatoires, `simulation_only = true`,
   mode `LABORATORY` ou `CHALLENGE_SIM`, schema et phase.
2. **Empreinte** : `report_fingerprint` recalculee sur le contenu courant.
3. **Dataset et compte** : empreinte dataset coherente, valeurs comptables
   numeriques.
4. **Session** : identifiant recalcule a partir de la strategie, de la
   configuration, du dataset, de l'horodatage et de la version du code.
5. **Journal** : sequence `0..N-1` continue, horodatage non decroissant,
   types et payloads valides, debut `REPLAY_STARTED`, unique
   `REPLAY_FINISHED` en derniere position, une seule session.
6. **Croisement** : nombre d'evenements, repartition `observability`,
   empreintes de depart, identite de session, equity/PnL final, politique de
   fin, nombre d'executions, reconciliation unique et conforme.
7. **Challenge** : si actif, un unique `CHALLENGE_FINALIZED` dont le verdict
   est identique a celui du rapport.

Chaque ecart produit un `Finding` avec `severity`, `code` et `message`. Les
erreurs rendent le cockpit non conforme ; les avertissements sont conserves
mais n'echouent qu'en mode `--strict`.

## 6. Observabilite du rapport

Ajout de la section :

```json
{
  "observability": {
    "journal_events": 16,
    "event_counts": {"ORDER_FILLED": 2, "REPLAY_FINISHED": 1},
    "first_ts_ns": 0,
    "last_ts_ns": 1767585600000000000,
    "last_event_type": "REPLAY_FINISHED",
    "replay_started_events": 2,
    "replay_finished_events": 1,
    "session_ids": ["S-f8ef7a6d33d7f122"],
    "chronological": true
  }
}
```

Aucune date de generation, aucun chemin absolu, aucun nom d'hote : la
reproductibilite octet pour octet du rapport est preservee.

## 7. Utilisation

```powershell
.\.venv\Scripts\python.exe -m etatmajor.cli cockpit `
    --report artifacts\example_report.json `
    --journal artifacts\example_journal.jsonl `
    --html artifacts\example_cockpit.html `
    --json artifacts\example_cockpit.json
```

Sortie attendue : `Status : PASS`, aucune constatation, code retour `0`.
Une empreinte modifiee produit `REPORT_FINGERPRINT_MISMATCH` et le code `3`.

## 8. Preuves d'execution

```text
Suite complete              : 564 passed
Tests cockpit                : 14 passed (11 unitaires + 3 integration)
Tests d'acceptation cockpit  : 3 passed
Architecture / no-network    : 142 passed
```

Rapport de reference :

```text
Bars / events   : 240 / 16
Equity          : 100005.31 USD
Net PnL         : +5.31 (+0.0053%)
Orders / fills  : 2 / 2
Fingerprint     : 4d0f37dc0db9ec09
Session         : S-f8ef7a6d33d7f122
Cockpit         : PASS
```

## 9. Limites

* Le cockpit est une vue **non signee** : il detecte une alteration
  accidentelle, pas une falsification deliberee qui recalcule toutes les
  empreintes.
* Il ne remplace ni un releve broker, ni un audit independant.
* Les tableaux sont bornes a 100 lignes (ordres, executions) et 40 evenements ;
  le JSON complet reste disponible separement.
* Le HTML est statique : pas de filtrage interactif, pas de JavaScript.
* Aucune metrique avancee de performance (profit factor, drawdown de courbe
  d'equity, walk-forward) : Phase 9.
* La CI distante reste indisponible ; les preuves sont locales Windows /
  Python 3.14.0.

## 10. Risques et suites

| Risque | Traitement |
| --- | --- |
| Confondre cockpit et validation statistique | le cockpit affiche l'integrite, pas une recommandation d'investissement |
| Evidence volumineuse | troncature d'affichage, snapshot JSON complet |
| Schema futurs | avertissement `SCHEMA_VERSION`, jamais une acceptation silencieuse |
| Performance Sniper quadratique | optimiser Market Intelligence avant replay 100k |

**Suite :** Phase 9 - metriques de performance, robustesse, separation
entrainement/validation/test et selection de strategie.

**Ne pas fusionner sans l'audit du chef de projet.**

# Vérification du chaînage des Pull Requests

**Date :** 2026-10-22 · **Branche d'audit :** `feat/mission-0-audit`
**Objet :** vérifier que la chaîne `main ← PR#1 ← PR#2` livre bien l'ensemble
des modifications sur `main`, et fixer l'ordre de revue en conséquence.

---

## 1. Graphe actuel (vérifié)

```text
5f1eb10  main                                 (socle : pyproject, configs, .gitignore)
   |
   +-- 1a1bea5 .. c0fdeab   feat/phase-2-replay-engine   (10 commits)  --> PR #1
          |
          +-- 22a95d2 .. 7a8648a   feat/mission-0-audit   (7 commits)   --> PR #2
```

| PR | Base | Tête | Commits | Diff | État |
| --- | --- | --- | --- | --- | --- |
| **#1** | `main` | `feat/phase-2-replay-engine` | 10 | 59 fichiers, +6 494 lignes | ouverte, non fusionnée |
| **#2** | `feat/phase-2-replay-engine` | `feat/mission-0-audit` | 7 | 21 fichiers, +2 993 / −5 lignes | ouverte, non fusionnée |

**Vérification d'ascendance :** `c0fdeab` (tête de la PR #1) est bien un
ancêtre de `7a8648a` (tête de la PR #2). La PR #2 **contient déjà** tous les
commits de la PR #1 : la fusion enchaînée ne duplique rien et ne perd rien.

## 2. Résultat attendu après chaque fusion

| Étape | Action | `main` après l'étape | Contenu sur `main` |
| --- | --- | --- | --- |
| 0 | état actuel | `5f1eb10` | socle seul (6 fichiers) |
| 1 | fusion de la PR #1 | `c0fdeab` (+ commit de fusion) | socle + Phase 2 complète (moteur de replay, 104 tests, CI, docs) |
| 2 | fusion de la PR #2 | `6d19338` (+ commit de fusion) | socle + Phase 2 + **audit MISSION 0** (18 commits au total) |

Simulation effectuée localement (`git merge --no-ff` sur une branche de
simulation, supprimée depuis) :

```text
SIMULATION 1 : fusion PR #1 (merge commit)
  main simule apres fusion PR #1 : c0fdeab
  commits de la PR #2 vs main simule : 7
   21 files changed, 2993 insertions(+), 5 deletions(-)

SIMULATION 2 : etat final apres fusion de la PR #2
  main simule final : 6d19338
  arbre final identique a feat/mission-0-audit : OUI (rien de perdu)
  commits total sur main simule : 18
```

**Conclusion :** l'arbre final de `main` est **strictement identique** à
`feat/mission-0-audit`. Le rapport d'audit, la matrice de conformité, les
preuves (`docs/audit/evidence/`) et les résultats de test archivés
(`tests/results/`) sont bien sur `main`, pas dans une branche secondaire.

## 3. Procédure de fusion recommandée

**Étape 1 — fusionner la PR #1 avec la stratégie « Merge commit ».**

Puis **changer la base de la PR #2** (`Edit` en haut à droite → *Base* →
`main`). Après ce changement, la PR #2 affiche exactement 7 commits et 21
fichiers : l'audit seul, sans réapparition du contenu de la Phase 2.

```text
PR #2 : base main  <-  tete feat/mission-0-audit   =>  7 commits, 21 fichiers
```

**Étape 2 — fusionner la PR #2.** `main` contient alors l'intégralité du
travail (18 commits).

### 3.1 Avertissement : ne pas utiliser « Squash and merge » sur la PR #1

Simulé également :

```text
SIMULATION 3 : si la PR #1 avait ete squash-mergee
  main simule (squash) : 302b19f
  commits de la PR #2 vs main squash : 17
   78 files changed, 9482 insertions(+)
```

Avec un squash, `main` ne contient plus l'historique de `c0fdeab` : le
diff de la PR #2 repart de la racine et **réaffiche les 78 fichiers** (les
deux PR confondues). Le contenu reste correct, mais la revue devient
illisible et le double comptage des modifications est trompeur.

**Solutions au cas où le squash aurait été utilisé :**

1. rebaser la branche d'audit sur `main` avant de fusionner :

   ```bash
   git fetch origin
   git checkout feat/mission-0-audit
   git rebase origin/main
   git push --force-with-lease origin feat/mission-0-audit
   ```

   puis retargeter la PR #2 sur `main` (diff ramené à l'audit seul) ;

2. ou fermer la PR #2 et en rouvrir une depuis `feat/mission-0-audit` vers
   `main` après le rebase.

## 4. Ordre de revue recommandé

| Rang | Objet | Vérification | Preuve attendue |
| --- | --- | --- | --- |
| 1 | PR #1 — socle de la Phase 2 | `git diff main...feat/phase-2-replay-engine` (59 fichiers) | `docs/PHASE2_REPORT.md` §8 (9 assertions couvertes) |
| 2 | PR #1 — CI | `.github/workflows/ci.yml` | la CI ne démarre qu'après fusion (le workflow est introduit par la PR #1) ; logique déjà validée localement : `tests/results/2026-10-22-delivery/ci-workflow-simulation.txt` |
| 3 | PR #2 — audit | `git diff feat/phase-2-replay-engine...feat/mission-0-audit` (21 fichiers) | `docs/audit/INITIAL_AUDIT.md` (matrice de conformité §7) |
| 4 | PR #2 — preuves | `docs/audit/evidence/`, `tests/results/2026-10-22-mission-0/` | résultats reproductibles (104 tests, 86 % de couverture) |
| 5 | Graphe après fusion | `git log --graph --oneline main` | 18 commits, arbre identique à `feat/mission-0-audit` |

## 5. Ce que la revue doit trancher

1. la **matrice de conformité** de l'audit (M1 ~55 %, M2 ~80 %, M3 ~30 %,
   M4 ~50 %, M5→M16 absentes) ;
2. l'**ordre des corrections** C1 → C2 → C3 (aucune nouvelle capacité) ;
3. le **profil The5ers de référence** : `docs/propfirm/THE5ERS_REFERENCE.md`
   et `configs/prop_firms/the5ers_high_stakes_new_2500.draft.yaml`
   (statut `DRAFT`, non utilisable pour conclure) ;
4. l'**autorisation écrite** requise avant toute utilisation réelle d'un EA
   (conditions générales The5ers du 20 octobre 2026).

## 6. Sécurité — contrôle effectué

| Contrôle | Résultat |
| --- | --- |
| Jeton `ghp_…` dans l'arbre de travail | 0 occurrence |
| Jeton `ghp_…` dans l'historique git (tous les commits, toutes branches) | 0 occurrence |
| Jeton / mot de passe dans les bundles de transfert | 0 occurrence |
| Mot de passe du compte dans l'arbre ou l'historique | 0 occurrence |
| Fichiers sensibles versionnés (`.env`, `.pem`, `.key`, `.netrc`) | aucun |
| Valeurs réelles dans `.env.example` | aucune (commentaires uniquement) |

Les secrets n'ont existé que dans des fichiers temporaires (`/tmp`) supprimés
immédiatement après usage, et n'ont jamais été écrits dans `.git/config`.

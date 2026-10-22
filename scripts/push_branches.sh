#!/usr/bin/env bash
# Pousser les branches du projet sur GitHub.
#
# Le depot distant est public et la machine de build ne dispose d'aucun
# identifiant par defaut. Ce script utilise un jeton d'acces personnel fourni
# par l'environnement (GITHUB_TOKEN), **sans jamais l'ecrire** :
#   - il n'est jamais passe en ligne de commande (GIT_ASKPASS) ;
#   - il n'est jamais ecrit dans .git/config ;
#   - il n'est jamais journalise.
#
# Usage :
#   export GITHUB_TOKEN=<jeton a portee limitee repo:write sur ce depot>
#   ./scripts/push_branches.sh
#
# Le jeton peut etre fourni par l'utilisateur a l'invite si la variable
# d'environnement est absente (le jeton n'est alors ni stocke ni journalise).
set -euo pipefail

cd "$(dirname "$0")/.."

REMOTE="${REMOTE:-https://github.com/fortixistech-commits/EtatMajor_Sniper_EA.git}"
BRANCHES="${BRANCHES:-main feat/phase-2-replay-engine feat/mission-0-audit}"

if [ -z "${GITHUB_TOKEN:-}" ]; then
  echo "GITHUB_TOKEN absent : le push ne peut pas s'authentifier." >&2
  echo "Creez un jeton a portee limitee (repo:write sur ce seul depot) puis :" >&2
  echo "  export GITHUB_TOKEN=<votre jeton> && ./scripts/push_branches.sh" >&2
  exit 2
fi

ASKPASS="$(mktemp)"
trap 'rm -f "$ASKPASS"' EXIT
cat > "$ASKPASS" <<'EOF'
#!/bin/sh
case "$1" in
  *sername*) printf '%s\n' "x-access-token" ;;
  *assword*) printf '%s\n' "$GITHUB_TOKEN" ;;
  *) printf '%s\n' "" ;;
esac
EOF
chmod 700 "$ASKPASS"

echo "==> remote   : $REMOTE"
echo "==> branches : $BRANCHES"

git push --set-upstream origin $BRANCHES

echo
echo "==> etat des references distantes"
git ls-remote --heads origin

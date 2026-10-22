"""Challenge Engine : le profil The5ers comme systeme de contraintes.

Le profil est une **donnee versionnee**, jamais du code. Il porte des regles
verifiees et datees ; les regles qui ne sont pas verifiees sont declarees
explicitement et le moteur ne peut pas conclure sur un profil incomplet.

Regle de conception appliquee ici : une regle ambigue est evaluee sous
**toutes** ses interpretations, et le verdict le plus defavorable l'emporte.
Une campagne n'est `PASSED` que si toutes les interpretations le sont.
"""

# Rapport - Phase 3 : Market Intelligence et detecteur de regimes

**Projet :** ETAT-MAJOR SNIPER EA - **Date :** 2026-10-22
**Branche :** `fix/phase-c-corrections`
**Porte visee :** G3
**Verdict :** **PASS**, avec limites documentees.

---

## 1. Objectif

Produire une lecture du terrain **explicable**, calculee uniquement sur les
bougies visibles, et utilisable par les phases suivantes :

- classer le regime (tendance / range / indetermine) ;
- mesurer la force de tendance et le momentum ;
- mesurer la volatilite absolue et relative ;
- decrire la structure (sommets et creux, canaux) ;
- verifier l'alignement avec un timeframe superieur cloture ;
- tenir compte de la qualite des donnees dans la confiance ;
- exposer chaque variable et chaque motif dans la decision.

Cette phase ne produit **aucun signal d'entree** et ne cherche pas d'avantage
statistique.

## 2. Etat initial

`src/etatmajor/sniper/regime.py` fournissait :

- un regime EMA rapide/lente avec pente et position du prix ;
- un etat de volatilite base sur le rapport ATR courant / ATR precedent ;
- une confiance simple et des motifs textuels.

Il manquait : ADX et DI, RSI, taux de variation, percentile ATR, structure de
marche, multi-timeframe, prise en compte des barres manquantes, et exposition
de l'ensemble dans la decision du moteur.

## 3. Fichiers

| Fichier | Nature |
| --- | --- |
| `src/etatmajor/sniper/market_intelligence.py` | **nouveau** - mesures, classifications, agregation HTF, confiance |
| `src/etatmajor/sniper/engine.py` | instantane expose dans `SniperDecision`, garde de qualite des donnees |
| `tests/unit/test_market_intelligence.py` | **nouveau** - 26 tests |
| `configs/instruments.toml` | inchange (consomme en phase 5) |

## 4. Decisions techniques

### 4.1 Mesures standards, sans dependance

- ADX / +DI / -DI : lissage de Wilder, retour `0` si l'historique est
  insuffisant ou si le True Range cumule est nul.
- RSI : Wilder, `50` sur une serie immobile (aucune pression interpretable).
- ATR percentile : rang parmi les ATR roulants precedents, ex aequo comptes a
  moitie. Une volatilite constante donne `0.5`, pas `1.0`.
- Structure : swings locaux stricts confirmes a gauche et a droite
  (`left=2`, `right=2`) ; fallback sur deux canaux consecutifs quand aucun
  swing n'est confirme.
- Evenement de structure : franchissement **a la bougie courante** d'un
  dernier sommet/creux, pas un etat permanent.

### 4.2 Multi-timeframe sans look-ahead

Les bougies 1m sont agregees par buckets temporels. Un bucket n'est retourne
que si `bucket_end <= last_visible_close`. Une bougie superieure en formation
est donc invisible pour la decision. La duree de base est explicite ou
inferree par la mediane des ecarts, robuste aux coupures de marche.

### 4.3 Confiance

La confiance combine :

- la confiance du regime (base) ;
- la force ADX (bonus si forte, malus si absente) ;
- l'alignement de structure avec le regime (bonus/malus) ;
- l'alignement du timeframe superieur (bonus/malus) ;
- un facteur de qualite des donnees (`1 - 2 x taux de barres manquantes`,
  borne a `0.4`).

Elle est bornee dans `[0, 1]` et **informative** : elle n'est pas encore
calibree statistiquement. Son usage comme filtre dur appartient aux phases
G4/G5.

### 4.4 Qualite des donnees

`DataQualityAssessment` accepte directement un `DataQualityReport` du loader.
Le moteur s'abstient si le taux de barres manquantes depasse
`max_missing_ratio` (10 % par defaut) ; le motif cite le taux et le seuil.
Cette garde est volontairement conservatrice et separee du regime.

## 5. Integration au moteur

`SniperDecision` expose desormais `intelligence` (et `to_dict()` le serialise).
Le moteur calcule l'instantane **avant** le regime et reutilise son regime,
ce qui evite deux classifications divergentes. Les abstentions existantes
sont conservees : regime non tendanciel, contexte refuse, setup absent,
planification impossible.

## 6. Commandes et resultats

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\test_market_intelligence.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

- Tests cibles : **26 passes**.
- Suite complete : **467 passes, 0 echec** (local, Windows, Python 3.14.0).
- Nouveaux cas : 26 explicites + 3 tests d'architecture generes par le
  nouveau module = **29**.
- Aucune modification de l'artefact d'exemple : la phase n'ajoute pas de
  champ au rapport de replay.

## 7. Criteres d'acceptation

| Critere | Etat | Preuve |
| --- | --- | --- |
| Mesures sur bougies visibles uniquement | PASS | `test_future_bars_cannot_change_a_decision_taken_earlier` |
| Agregation HTF sans bougie incomplete | PASS | `test_aggregation_only_returns_closed_buckets` |
| ADX, DI et RSI bornes et directionnels | PASS | tests ADX / RSI |
| Percentile ATR robuste aux ex aequo | PASS | `test_percentile_rank_counts_ties_as_half`, `atr_percentile == 0.5` |
| Structure confirmee, fallback documente | PASS | `test_structure_prefers_confirmed_swings_when_available` |
| Evenement de structure non permanent | PASS | `test_a_break_of_structure_is_reported_only_on_the_crossing_bar` |
| Qualite des donnees prise en compte | PASS | baisse de confiance + abstention moteur |
| Instantane explicable et serialisable | PASS | motifs, `to_dict`, test JSON |
| Determinisme | PASS | deux evaluations identiques |
| Aucun signal d'entree ajoute | PASS | portee du module |

## 8. Limites

1. La confiance n'est pas calibree : elle ordonne des situations, elle ne
   predit pas une probabilite de succes.
2. Un seul timeframe superieur est evalue a la fois.
3. Les sessions restent un decoupage UTC simple ; les jours feries et les
   fermetures ne sont pas connus.
4. Le spread et la liquidite ne sont pas dans l'instantane ; ils restent
   verifies par `ContextFilter`.
5. Le percentile ATR depend de la fenetre visible ; un historique court
   produit une lecture instable (rendue visible par `bars_used`).
6. Aucune mesure de volume profile, d'order flow ou de liquidite de carnet.

## 9. Risques residuels

- **Surconfiance** : une serie synthetique tendancielle donne une confiance
  elevee alors qu'aucune conclusion de marche n'est possible. Mitigation :
  le module ne produit pas de signal et le rapport rappelle le caractere
  synthetique des donnees.
- **Faux alignement HTF** : peu de bougies superieures peuvent suffire au
  detecteur si sa periode lente est courte. Mitigation : `bars_used` est
  expose ; G4 devra exiger un minimum.

## 10. Recommandation

Passer a la Phase 4 : qualifier le Sniper Engine contre G4, notamment
l'utilisation de la confiance, la coherence structure/setup et l'absence de
contournement du plan.

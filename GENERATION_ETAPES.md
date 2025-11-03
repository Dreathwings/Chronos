# Étapes de la génération automatique

1. **Analyse du cours**
   - Lecture de la période de planification selon le semestre.
   - Agrégation des semaines autorisées et des objectifs déclarés par semaine.
   - Calcul de la charge totale à produire pour toutes les classes et sous-groupes.

2. **Préparation hebdomadaire**
   - Construction de la liste des semaines ouvertes à partir du 1er septembre de l'année scolaire concernée.
   - Recensement exhaustif des séances à placer pour la semaine courante avant de lancer les placements.
   - Initialisation du suivi de progression avec le tableau récapitulant les séances à planifier pour la semaine active.

3. **Ordonnancement des séances**
   - Progression hebdomadaire globale : toutes les séances de la semaine courante sont planifiées pour l'ensemble des cours avant de passer à la suivante.
   - Classement des séances selon la chronologie pédagogique : CM → SAE → TD → TP → Éval.
   - Priorisation des premiers jours ouvrés de la semaine afin de faciliter le respect de l'ordre pédagogique.
   - Pour chaque type, sélection des créneaux compatibles (jours ouvrés, salles, équipements, indisponibilités, périodes de fermeture).
   - Préférence pour les matinées lors des TD et pour les après-midis lors des TP, tout en respectant les disponibilités et les contraintes d'équipement.

4. **Affectation des intervenants**
   - Recherche d'un enseignant disponible en privilégiant la continuité pour une même classe ou sous-groupe.
   - Interprétation d'une séance hebdomadaire selon le type de cours :
     - CM : une occurrence unique pour l'ensemble des classes inscrites.
     - SAE : une occurrence par classe mobilisant deux enseignants en simultané.
     - TD : une occurrence par classe.
     - TP : une occurrence par demi-groupe de chaque classe.
   - Conversion des heures cibles en nombre de séances à assurer par enseignant : volume horaire ÷ durée d'une séance ÷ somme de toutes les séances prévues sur les semaines sélectionnées (après application des multiplicateurs groupes/enseignants).
   - Projection de cette répartition sur chaque semaine déclarée afin d'estimer le volume de séances attendu par enseignant.
   - Conversion de ces quotas hebdomadaires en heures en multipliant le nombre de séances prévues par la durée d'une séance pour chaque intervenant.
   - Détermination du nombre maximal de groupes hebdomadaires supportables par enseignant (volume horaire ÷ durée d'une séance ÷ objectif hebdomadaire) et exclusion des candidats dépassant ce plafond pour la semaine considérée.
   - Respect des allocations d'heures et de séances par enseignant et bascule automatique vers un autre intervenant lorsque le quota est atteint.

5. **Placement définitif**
   - Réservation de la salle la plus adaptée et création des séances dans la base.
   - Mise à jour du tableau hebdomadaire de progression et du pourcentage global.
   - En cas d'échec persistant en fin de semaine, déplanification ciblée des TD/TP déjà posés sur la semaine concernée pour libérer les créneaux bloquants avant une nouvelle tentative.

6. **Finalisation**
   - Vérification des heures restantes et émission d'éventuels avertissements (capacités, chronologie, indisponibilités).
   - Enregistrement du rapport de génération et clôture de la progression.

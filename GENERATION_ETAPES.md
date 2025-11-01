# Étapes de la génération automatique

1. **Analyse du cours**
   - Lecture de la période de planification selon le semestre.
   - Agrégation des semaines autorisées et des objectifs déclarés par semaine.
   - Calcul de la charge totale à produire pour toutes les classes et sous-groupes.

2. **Préparation hebdomadaire**
   - Construction de la liste des semaines ouvertes à partir du 1er septembre de l'année scolaire concernée.
   - Initialisation du suivi de progression avec le tableau récapitulant les séances à planifier pour la semaine active.

3. **Ordonnancement des séances**
   - Progression hebdomadaire globale : toutes les séances de la semaine courante sont planifiées pour l'ensemble des cours avant de passer à la suivante.
   - Classement des séances selon la chronologie pédagogique : CM → SAE → TD → TP → Éval.
   - Pour chaque type, sélection des créneaux compatibles (jours ouvrés, salles, équipements, indisponibilités, périodes de fermeture).

4. **Affectation des intervenants**
   - Recherche d'un enseignant disponible en privilégiant la continuité pour une même classe ou sous-groupe.
   - Respect des allocations d'heures par enseignant et bascule automatique vers un autre intervenant lorsque le quota est atteint.

5. **Placement définitif**
   - Réservation de la salle la plus adaptée et création des séances dans la base.
   - Mise à jour du tableau hebdomadaire de progression et du pourcentage global.

6. **Finalisation**
   - Vérification des heures restantes et émission d'éventuels avertissements (capacités, chronologie, indisponibilités).
   - Enregistrement du rapport de génération et clôture de la progression.

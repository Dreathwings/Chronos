# Étapes de génération des emplois du temps

1. **Initialisation de la semaine**
   - Les semaines autorisées sont identifiées à partir des fenêtres de planification du cours et des périodes de fermeture.
   - Les objectifs hebdomadaires (séances à générer) sont établis pour chaque semaine sélectionnée.

2. **Préparation du suivi**
   - Le suivi de progression enregistre pour chaque semaine l'objectif de séances à produire.
   - Le suivi affiche en temps réel l'avancement de la semaine active dans la fenêtre de progression.

3. **Collecte des séances**
   - Pour chaque semaine, la liste des séances est constituée pour toutes les classes associées au cours.
   - Les séances sont triées selon l'ordre de priorité : CM → SAE → Eval → TD → TP.

4. **Analyse des contraintes**
   - Les indisponibilités globales (fermetures) et individuelles (enseignants, classes) sont vérifiées pour la semaine.
   - Les contraintes de salles (capacité, ordinateurs, équipements) sont évaluées.

5. **Planification des séances**
   - Pour chaque séance, un enseignant est sélectionné en privilégiant la continuité avec les séances précédentes.
   - Les créneaux compatibles pour la classe et l'enseignant sont recherchés en tenant compte des ressources requises.
   - Le créneau optimal est choisi ; les autres créneaux disponibles sont conservés comme alternatives potentielles.

6. **Réaffectation si nécessaire**
   - Si une séance ne peut pas être placée, une réorganisation tente de libérer un créneau adapté.

7. **Bascule à la semaine suivante**
   - Lorsque toutes les séances d'une semaine sont planifiées, la génération passe à la semaine suivante.
   - Les séances non planifiées sont reportées et ajoutées à la fin de la liste de la semaine suivante.

8. **Finalisation**
   - Le suivi de progression est mis à jour avec les séances réellement générées pour chaque semaine.
   - Un journal récapitulatif est enregistré pour le cours avec les éventuels avertissements.

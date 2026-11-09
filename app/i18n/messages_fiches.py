"""Messages des fiches techniques et des combinaisons (codes ``fiche.*``, ``combinaison.*``, ``plat.*``).

Fichier propre à la piste « fiches techniques » : ``messages_fr`` et ``messages_en`` l'importent en fin de
module (``MESSAGES.update``). Clés stables : ne jamais les renommer.
"""

FR = {
    # Fiches techniques
    "fiche.plat_introuvable": "Ce plat est introuvable.",
    "fiche.composant_introuvable": "Ce composant n'existe pas dans ce restaurant.",
    "fiche.composant_archive": "Le composant « {composant} » est archivé : restaurez-le ou choisissez-en un autre.",
    "fiche.composant_doublon": "Le composant « {composant} » figure déjà dans cette fiche.",
    "fiche.doublon_dans_liste": "Un composant ne peut apparaître qu'une seule fois dans une fiche.",
    "fiche.unite_incompatible": (
        "Impossible d'exprimer « {composant} » en {unite} : ce composant se compte en {stock_unite}. "
        "Unités possibles : {unites}."
    ),
    "fiche.quantite_precision": (
        "La quantité doit être comprise entre 0,001 et 999 999 999,999, avec trois décimales au plus."
    ),
    "fiche.quantite_negligeable": (
        "Cette quantité est trop petite : une fois convertie en {stock_unite}, elle serait inférieure à 0,001."
    ),
    "fiche.rendement_invalide": (
        "Le rendement doit être supérieur à 0 et au plus égal à 1 (0,8 = 20 % de perte), "
        "avec quatre décimales au plus."
    ),
    "fiche.ligne_introuvable": "Cette ligne n'existe pas dans la fiche technique.",
    "fiche.ordre_incomplet": (
        "La liste doit contenir exactement les composants de la fiche, une seule fois chacun."
    ),
    "fiche.copie_sur_elle_meme": "Une fiche ne peut pas être copiée sur le même plat.",
    "fiche.source_vide": "La fiche à copier est vide : ajoutez d'abord des composants.",
    "fiche.cible_non_vide": (
        "Le plat « {plat} » a déjà une fiche de {lignes} ligne(s). Confirmez le remplacement pour l'écraser."
    ),
    "fiche.cible_requise": "Indiquez le plat de destination ou le nom de la variante à créer.",
    "fiche.cible_ambigue": "Indiquez soit un plat de destination, soit le nom d'une nouvelle variante, pas les deux.",
    "fiche.food_cost_invalide": "Le seuil de food cost doit être compris entre 1 et 100 %.",
    "fiche.cycle": "Cette recette se contiendrait elle-même : {chemin}.",
    "plat.nom_existant": "Un plat porte déjà ce nom.",
    # Combinaisons
    "combinaison.introuvable": "Cette combinaison est introuvable.",
    "combinaison.composition_requise": "Une combinaison doit contenir au moins un composant.",
    "combinaison.composant_doublon": "Un composant ne peut apparaître qu'une seule fois dans une combinaison.",
    "combinaison.composant_introuvable": "Un des composants n'existe pas dans ce restaurant.",
    "combinaison.composant_indisponible": (
        "Le composant « {composant} » est indisponible : réactivez-le avant de l'ajouter à une combinaison."
    ),
    "combinaison.composant_archive": (
        "Le composant « {composant} » est archivé : restaurez-le ou retirez-le de la combinaison."
    ),
    "combinaison.quantite_invalide": (
        "La quantité de chaque composant doit être comprise entre 0,001 et 9 999 999,999, "
        "avec trois décimales au plus."
    ),
    "combinaison.nom_requis": "Indiquez le nom de la combinaison.",
    "combinaison.nom_existant": "Une combinaison porte déjà ce nom.",
    "combinaison.prix_invalide": (
        "Le prix doit être supérieur à 0 et inférieur à 100 000 000, avec deux décimales au plus."
    ),
    "combinaison.photo_invalide": (
        "L'adresse de la photo doit commencer par http:// ou https:// et ne pas dépasser 500 caractères."
    ),
    "combinaison.tva_invalide": "Le taux de TVA doit être compris entre 0 et 100 %, avec deux décimales au plus.",
    "combinaison.devise_invalide": "La devise d'une combinaison est celle du restaurant ({devise}).",
    "combinaison.menu_invalide": "Ce menu n'appartient pas à ce restaurant.",
    "combinaison.archivee": "Cette combinaison est archivée : restaurez-la avant de la modifier.",
    "combinaison.restaurant_introuvable": "Restaurant introuvable.",
}

EN = {
    "fiche.plat_introuvable": "Dish not found.",
    "fiche.composant_introuvable": "This ingredient does not exist in this restaurant.",
    "fiche.composant_archive": "Ingredient \"{composant}\" is archived: restore it or pick another one.",
    "fiche.composant_doublon": "Ingredient \"{composant}\" is already in this recipe.",
    "fiche.doublon_dans_liste": "An ingredient can only appear once in a recipe.",
    "fiche.unite_incompatible": (
        "Cannot express \"{composant}\" in {unite}: this ingredient is counted in {stock_unite}. "
        "Possible units: {unites}."
    ),
    "fiche.quantite_precision": "The quantity must be between 0.001 and 999,999,999.999, with at most three decimals.",
    "fiche.quantite_negligeable": "This quantity is too small: converted to {stock_unite} it would be below 0.001.",
    "fiche.rendement_invalide": "Yield must be above 0 and at most 1 (0.8 = 20% loss), with at most four decimals.",
    "fiche.ligne_introuvable": "This line does not exist in the recipe.",
    "fiche.ordre_incomplet": "The list must contain exactly the recipe's ingredients, once each.",
    "fiche.copie_sur_elle_meme": "A recipe cannot be copied onto the same dish.",
    "fiche.source_vide": "The recipe to copy is empty: add ingredients first.",
    "fiche.cible_non_vide": "Dish \"{plat}\" already has a recipe of {lignes} line(s). Confirm replacement to overwrite it.",
    "fiche.cible_requise": "Provide the target dish or the name of the variant to create.",
    "fiche.cible_ambigue": "Provide either a target dish or a new variant name, not both.",
    "fiche.food_cost_invalide": "The food cost threshold must be between 1 and 100%.",
    "fiche.cycle": "This recipe would contain itself: {chemin}.",
    "plat.nom_existant": "A dish already has this name.",
    "combinaison.introuvable": "Combination not found.",
    "combinaison.composition_requise": "A combination must contain at least one ingredient.",
    "combinaison.composant_doublon": "An ingredient can only appear once in a combination.",
    "combinaison.composant_introuvable": "One of the ingredients does not exist in this restaurant.",
    "combinaison.composant_indisponible": "Ingredient \"{composant}\" is unavailable: re-enable it before adding it.",
    "combinaison.composant_archive": "Ingredient \"{composant}\" is archived: restore it or remove it.",
    "combinaison.quantite_invalide": (
        "Each ingredient quantity must be between 0.001 and 9,999,999.999, with at most three decimals."
    ),
    "combinaison.nom_requis": "Enter the combination name.",
    "combinaison.nom_existant": "A combination already has this name.",
    "combinaison.prix_invalide": "The price must be above 0 and below 100,000,000, with at most two decimals.",
    "combinaison.photo_invalide": "The photo address must start with http:// or https:// and be at most 500 characters.",
    "combinaison.tva_invalide": "The VAT rate must be between 0 and 100%, with at most two decimals.",
    "combinaison.devise_invalide": "A combination uses the restaurant's currency ({devise}).",
    "combinaison.menu_invalide": "This menu does not belong to this restaurant.",
    "combinaison.archivee": "This combination is archived: restore it before editing.",
    "combinaison.restaurant_introuvable": "Restaurant not found.",
}

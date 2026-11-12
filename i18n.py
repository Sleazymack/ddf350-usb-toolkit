"""Small display-only FR/EN catalogue; no device access or writes on import."""
import json
import os
from pathlib import Path
import re
import tkinter as tk

LANGUAGES=('fr','en')
DEFAULT_LANGUAGE='en'
_language=DEFAULT_LANGUAGE
EN={
    'Ancien lecteur de démarrage : prépare un nouveau fichier.':'Legacy startup player: prepare a new target.',
    'Photo / GIF…':'Photo / GIF…', 'Photo / GIF':'Photo / GIF',
    'Choisir une photo ou un GIF…':'Choose a photo or GIF…',
    'Photo centrée à 80 % · PNG, JPEG ou BMP.':'Centered photo at 80% · PNG, JPEG or BMP.',
    'GIF facultatif et expérimental : un blocage reste possible.':'GIF playback is optional and experimental: the radio may freeze.',
    'GIF : moins de 280 Ko, 5 images/s maximum, 4 s maximum (2 à 20 images).':'GIF: under 280 kB, up to 5 fps, up to 4 s (2–20 frames).',
    'Chaque image du GIF doit durer entre 200 et 1 000 ms (5 images/s maximum).':'Each GIF frame must last 200–1,000 ms (up to 5 fps).',
    'Le GIF doit faire moins de 280 Ko (280 000 octets), avant et après conversion.':'The GIF must be under 280 kB (280,000 bytes), before and after conversion.',
    'Le GIF doit contenir 2 à 20 images et durer 4 secondes maximum.':'A GIF must contain 2–20 frames and last no more than 4 seconds.',
    'Le GIF décompressé dépasse 64 mégapixels.':'The decoded GIF exceeds 64 megapixels.',
    'Photo de démarrage ou firmware non reconnu.':'Unrecognized startup photo or firmware.', 
    'GIF Drift':'Drift GIF',
    'Le GIF intégré ne correspond pas à la boucle prévue.':'The built-in GIF does not match the expected animation.',
    'Fond par défaut':'Default background','Fond par défaut rétabli.':'Default background restored.',
    'Photo trop grande.':'Photo is too large.',
    'Fond du dashboard':'Dashboard background','Couleur unie':'Solid color',
    'Photo de fond…':'Background photo…','Couleur du fond entier…':'Full background color…',
    'Rétablir le fond d’origine':'Restore stock background','Photo appliquée à tout le dashboard.':'Photo applied across the dashboard.',
    'Couleur appliquée à tout le dashboard.':'Color applied across the dashboard.',
    'Couleurs appliquées à tout le dashboard.':'Theme applied across the dashboard.',
    'Fond d’origine rétabli en haut du dashboard.':'Stock upper background restored.',
    'Photo et démarrage trop volumineux ensemble : réduis le nombre d’images du GIF ou garde le démarrage d’origine.':'Photo and startup media exceed the available space together. Reduce the GIF frame count or keep the original startup.',
    'Choisis une photo fixe PNG, JPEG, BMP ou WebP (4096 px maximum).':'Choose a still PNG, JPEG, BMP or WebP photo (up to 4096 px).',
    'Image ou GIF…':'Image or GIF…',
    'Images/s':'FPS','Images max.':'Frame limit','images':'frames','16 couleurs':'16 colors',
    'Rejouer':'Replay','Utiliser ce rendu':'Use this preview','Rendu sélectionné':'Preview selected',
    'Actualiser l’aperçu':'Update preview','Aperçu':'Preview','Détails du média':'Media details',
    'Voir le message…':'View message…',
    'Vitesse · images/s':'Speed · frames/s', 'Images maximum':'Maximum frames',
    'Convertir et prévisualiser · 16 couleurs':'Convert and preview · 16 colors',
    'Utiliser ce rendu au démarrage':'Use this result at startup',
    'Rendu converti : ':'Converted result: ', 'Source : ':'Source: ',
    ' images/s · vitesse ×':' frames/s · speed ×',
    'Rendu à incorporer. Après un changement de réglage, reconvertis avant de l’utiliser.':'Result awaiting incorporation. After changing settings, convert again before using it.',
    'Ce rendu sera incorporé au prochain transfert.':'This result will be incorporated in the next transfer.',
    'Auto conserve la durée si possible, sinon accélère la séquence entière pour tenir en 4 s. Les GIF longs sont réduits à 40 images maximum sur toute leur durée. Le réglage images/s change la vitesse de lecture. Les images fixes restent affichées 2 s. Aperçu en 16 couleurs ; rendu LCD expérimental.':'Auto preserves duration when possible; otherwise it speeds up the entire sequence to fit 4 s. Longer GIFs are sampled across their full duration into at most 40 frames. Frames/s changes playback speed. Still images display for 2 s. The preview uses 16 colors; LCD rendering is experimental.',
    'Choisis une vitesse de 1 à 60 images par seconde, ou Auto.':'Choose a speed of 1 to 60 frames per second, or Auto.',
    'Choisis entre 2 et 40 images maximum.':'Choose between 2 and 40 maximum frames.',
    'Source trop grande : 600 images et 64 mégapixels cumulés maximum.':'Source too large: up to 600 frames and 64 megapixels combined.',
    'La durée des images du GIF est invalide (10 à 655350 ms).':'GIF frame duration is invalid (10 to 655350 ms).',
    'Vitesse trop basse : minimum ':'Speed too low: minimum ',
    ' images/s pour tenir en 4 secondes.':' frames/s to fit within 4 seconds.',
    'Vitesse incompatible avec les limites du lecteur : 10 à 1000 ms par image, 4 s maximum.':'Speed incompatible with player limits: 10 to 1000 ms per frame, up to 4 s total.',
    'Écran de démarrage':'Startup screen',
    'Facultatif : garde le démarrage d’origine ou choisis ton image / GIF. Aucun média n’est inclus par défaut.':'Optional: keep the original startup or choose your image / GIF. No media is included by default.',
    'Garder le démarrage d’origine':'Keep original startup',
    'Choisir une image ou un GIF…':'Choose an image or GIF…',
    'Média sélectionné : ':'Selected media: ',
    'Démarrage d’origine sélectionné.':'Original startup selected.',
    'Rejouer l’aperçu':'Replay preview',
    'Conversion du média…':'Converting media…',
    'Images et GIF':'Images and GIF',
    ' images · ':' frames · ', ' couleurs':' colors',
    'PNG / JPEG / BMP : affichage 2 s. GIF : 40 images maximum, 4 s maximum, 10 à 1000 ms par image. Conversion à 16 couleurs, 128 × 160 maximum ; l’aperçu montre la mise à l’échelle réelle. Lecture expérimentale, rendu LCD à vérifier sur la radio.':'PNG / JPEG / BMP: displayed for 2 s. GIF: up to 40 frames, 4 s total, 10 to 1000 ms per frame. Converted to 16 colors, up to 128 × 160; the preview shows actual scaling. Experimental playback; check LCD rendering on the radio.',
    'Le média doit être un fichier local ordinaire.':'Media must be a regular local file.',
    'Le média dépasse la limite de 25 Mo ou est vide.':'Media exceeds the 25 MB limit or is empty.',
    'Le média a changé pendant sa lecture.':'Media changed while being read.',
    'Formats acceptés : PNG, JPEG, BMP ou GIF.':'Accepted formats: PNG, JPEG, BMP or GIF.',
    'Image trop grande : 4096 pixels par côté et 8 mégapixels maximum.':'Image too large: up to 4096 pixels per side and 8 megapixels.',
    'Animation trop grande : 40 images et 64 mégapixels cumulés maximum.':'Animation too large: up to 40 frames and 64 megapixels combined.',
    'Pour une animation, utilise un GIF ; les PNG animés ne sont pas acceptés.':'Use a GIF for animation; animated PNG files are not supported.',
    'Chaque image du GIF doit durer entre 10 et 1000 ms.':'Each GIF frame must last between 10 and 1000 ms.',
    'Le GIF dépasse 4 secondes ; raccourcis-le avant importation.':'GIF exceeds 4 seconds; shorten it before importing.',
    'Le fichier image est illisible, incomplet ou trop grand.':'The image file is unreadable, incomplete or too large.',
    'Palette invalide.':'Invalid palette.',
    'Échec de vérification du média converti.':'Converted media verification failed.',
    'Le GIF converti dépasse 310 000 octets ; simplifie-le ou réduis ses images.':'Converted GIF exceeds 310,000 bytes; simplify it or reduce its frames.',
    'Radio':'Radio','PC':'PC','Bloc':'Block','Style':'Style',
    'Zones et blocs':'Zones and blocks','Zone du bloc sélectionné':'Selected block zone',
    'Chiffres':'Numbers','Pile':'Battery','Activer les zones A / B':'Enable A / B zones',
    'Déplace les blocs dans les grilles. Les menus restent conservés.':'Move blocks in the grids. Menus are preserved.',
    'Zones A / B activées.':'A / B zones enabled.','Zone modifiée.':'Zone changed.',
    'Pas assez de place dans cette zone.':'Not enough room in this zone.',
    'MENUS CONSERVÉS':'MENUS PRESERVED',
    'Animation d’allumage · drift · 4 s (expérimental)':'Startup animation · drift · 4 s (experimental)',
    'Le fichier officiel 2.0.5 est déjà disponible et vérifié.\n\nPour une radio plus ancienne, la migration dépend aussi de son programme de démarrage et doit suivre la procédure officielle du fabricant.\n\nAprès cette migration, confirme HW 1.0 / logiciel 2.0.5 pour personnaliser la radio ici.':'The official 2.0.5 file is already available and verified.\n\nFor an older radio, migration also depends on its bootloader and must follow the manufacturer’s official procedure.\n\nAfter migration, confirm HW 1.0 / software 2.0.5 to customize the radio here.',
    'Personnaliser la radio':'Customize radio', 'Jouer sur PC':'Play on PC',
    'DDF-350 · Personnaliser et jouer':'DDF-350 · Customize and play',
    'Personnaliser la télécommande':'Customize the transmitter',
    'Choisir le dashboard':'Choose dashboard', 'Personnaliser':'Customize',
    'Brancher la radio':'Connect the radio', 'Installer sur la radio':'Install on radio',
    'Redémarrer et essayer':'Restart and test', 'ÉTAPE ':'STEP ',
    'Retour':'Back', 'Continuer':'Continue', 'Réduire pour jouer':'Minimize to play',
    'Composition personnelle':'Custom dashboard',
    'Place tes jauges et choisis leurs couleurs.':'Place your gauges and choose their colors.',
    'Quelle version est affichée ?':'Which version is displayed?',
    'Crée ton dashboard, puis installe-le sur la radio depuis cette application.\nPour commencer, vérifie la version dans les informations de la radio : HW 1.0 / logiciel 2.0.5.':'Create your dashboard, then install it on the radio from this app.\nFirst, check the radio information: HW 1.0 / software 2.0.5.',
    '1 · Modifier le dashboard · ma radio est en 2.0.5 / HW 1.0':'1 · Customize dashboard · my radio is 2.0.5 / HW 1.0',
    'Autre version · mise à jour 2.0.5':'Other version · update to 2.0.5',
    '2 · Activer la télécommande sur PC · CH1 / CH2':'2 · Activate radio on PC · CH1 / CH2',
    'Choisis une présentation de départ. Tu pourras ensuite régler les jauges et leurs couleurs.':'Choose a starting layout. You can then adjust the gauges and their colors.',
    "L'accueil constructeur":'Manufacturer dashboard', "Le thème d'origine, quatre voies":'Original theme, four channels',
    'Les six voies sur un seul écran':'All six channels on one screen', 'CH1 à CH6':'CH1 to CH6',
    'Créer une composition personnelle':'Create a custom layout', 'Présentation sélectionnée : ':'Selected layout: ',
    'Modifier le placement et les couleurs…':'Edit positions and colors…', 'USB rapide · 1 ms':'Fast USB · 1 ms',
    'Les menus de la radio sont conservés. Les nouvelles présentations sont expérimentales.':'Radio menus are preserved. New layouts are experimental.',
    '1. Éteins le véhicule et la radio.\n2. Retire la batterie de la radio.\n3. Branche son câble USB au PC.\n4. Maintiens CH3 + CH4 + Power jusqu’au bip.':'1. Switch off the vehicle and radio.\n2. Remove the radio battery.\n3. Connect its USB cable to the PC.\n4. Hold CH3 + CH4 + Power until the beep.',
    'Le bip a retenti · détecter la radio':'I heard the beep · detect radio',
    'Radio détectée · sauvegarde, transfert et vérification automatiques.\nGarde l’USB branché jusqu’au message de déconnexion.':'Radio detected · automatic backup, transfer and verification.\nKeep USB connected until instructed to disconnect.',
    'Clique sur « Installer sur la radio », puis accepte la demande Windows.':'Click “Install on radio”, then accept the Windows prompt.',
    'Journal de l’installation':'Installation log', 'Un firmware ou un matériel inconnu est refusé.':'Unknown firmware or hardware is rejected.',
    'Le transfert et sa relecture ont réussi.\n1. Laisse l’USB débranché et remets la batterie.\n2. Allume avec Power uniquement.\n3. Vérifie ton dashboard et les commandes.\nPour jouer sur PC, rebranche ensuite l’USB en mode normal.\nLa lecture CH1/CH2 reprend automatiquement dans cette application.':'Transfer and readback succeeded.\n1. Keep USB disconnected and refit the battery.\n2. Switch on using Power only.\n3. Check the dashboard and controls.\nTo play on PC, reconnect USB in normal mode.\nCH1/CH2 reading resumes automatically in this app.',
    'Voir la sauvegarde et le compte rendu':'Open backup and report',
    'Sélectionner le firmware officiel':'Select official firmware',
    'Aucun firmware constructeur n’est inclus dans l’application.\n1. Ouvre la page DumboRC et obtiens la version 2.0.5.\n2. Extrais l’archive sur ton PC.\n3. Sélectionne son fichier DDF.bin ci-dessous.':'No manufacturer firmware is included in the app.\n1. Open the DumboRC page and obtain version 2.0.5.\n2. Extract the archive on your PC.\n3. Select its DDF.bin file below.',
    '1 · Ouvrir la page officielle DumboRC':'1 · Open the official DumboRC page',
    '2 · Choisir le fichier DDF.bin officiel 2.0.5…':'2 · Select official 2.0.5 DDF.bin…',
    'Fichier vérifié : ':'Verified file: ',
    'Aucun fichier sélectionné. Seul l’original 2.0.5 exact sera accepté.':'No file selected. Only the exact original 2.0.5 is accepted.',
    'Si le téléchargement 2.0.5 est indisponible sur le site, demande-le au fabricant.\nUne autre version ou un fichier déjà modifié sera refusé.':'If the 2.0.5 download is unavailable, request it from the manufacturer.\nAnother version or an already modified file will be rejected.',
    'Passer à la version officielle 2.0.5':'Update to official version 2.0.5',
    'Aucun firmware constructeur n’est inclus. Obtiens la version 2.0.5 sur le site DumboRC.\n\nDepuis une version plus ancienne, la procédure dépend aussi du programme de démarrage installé. Cette migration doit suivre la procédure officielle.\n\nAprès la mise à jour, reviens confirmer HW 1.0 / logiciel 2.0.5 pour installer ton dashboard ici.':'No manufacturer firmware is included. Obtain version 2.0.5 from DumboRC.\n\nFor an older version, the procedure also depends on the installed bootloader. Follow the official upgrade procedure.\n\nAfter updating, return and confirm HW 1.0 / software 2.0.5 to install your dashboard here.',
    'Ouvrir le téléchargement et la procédure officiels':'Open official download and instructions',
    'Revenir à la vérification':'Return to version check', 'Préparation impossible':'Preparation failed',
    'Composition à vérifier':'Check layout', 'Recherche de la radio…':'Searching for radio…',
    'DDF-350 détectée. Tu peux continuer.':'DDF-350 detected. You can continue.',
    'Préparation de l’installation · accepte la demande Windows…':'Preparing installation · accept the Windows prompt…',
    'Fichier du dashboard préparé et vérifié.':'Dashboard file prepared and verified.',
    'Lancement du processus administrateur. Windows peut demander confirmation ; si l’application est déjà administrateur, aucune nouvelle fenêtre n’est nécessaire.':'Starting the administrator process. Windows may ask for confirmation; if the app is already elevated, no new prompt is needed.',
    'Processus d’installation lancé. Attente de son premier compte rendu…':'Installation process started. Waiting for its first report…',
    'Le transfert a été interrompu. Débranche l’USB et garde la radio éteinte. Consulte le dossier de sauvegarde avant de réessayer.':'Transfer was interrupted. Disconnect USB and keep the radio off. Check the backup folder before retrying.',
    'Lecture CH1/CH2 · disponible après branchement USB normal':'CH1/CH2 reading · available in normal USB mode',
    'USB · recherche de la radio · lecture automatique active':'USB · searching for radio · automatic reading active',
    'USB · en attente de la radio · reconnexion automatique':'USB · waiting for radio · automatic reconnection',
    'USB actif · CH1 : ':'USB active · CH1: ', ' · lecture automatique':' · automatic reading',
    'USB connecté · attente de nouvelles données CH1/CH2':'USB connected · waiting for new CH1/CH2 data',
    'MODE PC · LECTURE EN DIRECT':'PC MODE · LIVE INPUT', 'Activer la télécommande sur PC':'Activate radio on PC',
    'Laisse cette application ouverte ou réduite. La lecture recherche la radio et se reconnecte automatiquement.':'Keep this app open or minimized. It searches for the radio and reconnects automatically.',
    'Allume la radio normalement avec Power, puis branche l’USB.\nLes mouvements CH1 et CH2 apparaissent ci-dessous, sans lancer Python.':'Switch on the radio normally using Power, then connect USB.\nCH1 and CH2 movements appear below without launching Python.',
    'CH1 · Direction':'CH1 · Steering', 'CH2 · Accélération / frein':'CH2 · Throttle / brake',
    'Activer automatiquement à l’ouverture de Windows · démarrage réduit':'Start automatically with Windows · minimized',
    'Démarrage automatique':'Windows startup', 'Démarrage Windows activé pour ton compte. L’application démarrera réduite en mode PC.':'Windows startup enabled for your account. The app will start minimized in PC mode.',
    'Démarrage Windows désactivé.':'Windows startup disabled.',
    'Icône Windows indisponible. La fenêtre reste accessible dans la barre des tâches.':'Notification icon unavailable. The window remains accessible in the taskbar.',
    'Synchronisation : ':'Synchronization: ', 'Installation en cours':'Installation in progress',
    'Attends le message de déconnexion avant de fermer.':'Wait for the disconnect instruction before closing.',
    'Attends le message de déconnexion et débranche l’USB avant de fermer.':'Wait for the disconnect instruction and unplug USB before closing.',
    'Ligne du journal illisible.':'Unreadable log entry.', 'DDF-350 · CH1/CH2 actifs':'DDF-350 · CH1/CH2 active',
    'DDF-350 · en attente de la télécommande':'DDF-350 · waiting for radio', 'Ouvrir DDF-350':'Open DDF-350',
    'Quitter la synchronisation':'Exit synchronization',
    'Icône de synchronisation disponible sur Windows uniquement.':'Synchronization icon is available on Windows only.',
    'Personnaliser le dashboard':'Customize dashboard', 'Jauge':'Gauge', 'Style et fichiers':'Style and files',
    'Jauge sélectionnée':'Selected gauge', 'Voie':'Channel', 'Forme':'Shape', 'Ajouter':'Add',
    'Barre':'Bar', 'Demi-cercle':'Semicircle', 'Couleur de la jauge':'Gauge color',
    'Supprimer cette jauge':'Delete this gauge', 'Couleurs de la zone':'Panel colors',
    'Bleu drift':'Drift blue', 'Rouge nuit':'Night red', 'Menthe':'Mint',
    'Choisir le fond':'Choose background', 'Fond de la zone centrale':'Central panel background',
    'Importer une disposition JSON':'Import JSON layout', 'Exporter la disposition JSON':'Export JSON layout',
    'Déplace les jauges dans la zone quadrillée. Le haut, le bas et les menus sont conservés.':'Drag gauges within the grid. The top, bottom and menus are preserved.',
    'ÉCRAN 240 × 320 · APERÇU SCHÉMATIQUE':'240 × 320 SCREEN · SCHEMATIC PREVIEW',
    'Les couleurs s’appliquent seulement\nà la zone centrale et à ses jauges.':'Colors apply only to\nthe central panel and its gauges.',
    "Les couleurs s'appliquent seulement\nà la zone centrale et à ses jauges.":'Colors apply only to\nthe central panel and its gauges.',
    'Choisis une jauge, puis glisse-la sur la grille.':'Select a gauge, then drag it onto the grid.',
    'Disposition chargée.':'Layout loaded.', 'Modification refusée : ':'Change rejected: ',
    'Voie modifiée.':'Channel changed.', 'Forme modifiée.':'Shape changed.',
    'Couleur de la jauge modifiée.':'Gauge color changed.', 'Fond de la zone centrale modifié.':'Central background changed.',
    'Palette appliquée à la zone centrale.':'Palette applied to the central panel.',
    'Jauge déplacée.':'Gauge moved.', 'Jauge supprimée.':'Gauge deleted.', 'Jauge placée sur la grille.':'Gauge placed on the grid.',
    ' ajouté. Tu peux maintenant le déplacer.':' added. You can now move it.',
    'Garde au moins une jauge. Tu peux changer sa forme ou sa voie.':'Keep at least one gauge. You can change its shape or channel.',
    'Les six voies sont déjà présentes. Supprime une jauge pour la remplacer.':'All six channels are present. Delete a gauge to replace it.',
    'Pas assez de place pour cette forme. Déplace ou supprime une autre jauge.':'Not enough space for this shape. Move or delete another gauge.',
    'Seule la zone centrale quadrillée est modifiable.':'Only the central grid panel is editable.',
    'Position refusée : ':'Position rejected: ', 'Déplacement annulé : ':'Move cancelled: ', 'Déplacement annulé.':'Move cancelled.',
    'Glisse la jauge. Échap annule le déplacement.':'Drag the gauge. Escape cancels the move.',
    'Relâche pour placer la jauge ici.':'Release to place the gauge here.',
    'MODÈLE':'MODEL', 'modèle 01':'model 01', 'ZONE CONSERVÉE':'PRESERVED AREA',
    'ZONE MODIFIABLE · 6 × 4':'EDITABLE AREA · 6 × 4', 'BAS CONSERVÉ · VALEURS ILLUSTRATIVES':'PRESERVED FOOTER · SAMPLE VALUES',
    'Importer une disposition':'Import layout', 'Exporter la disposition':'Export layout', 'Disposition JSON':'JSON layout',
    'Disposition JSON enregistrée.':'JSON layout saved.', 'Disposition non chargée':'Layout not loaded',
    'Enregistrement impossible':'Unable to save', 'Choisir un nouveau nom':'Choose a new name',
    'Choisis un nom se terminant par .json.':'Choose a name ending in .json.',
    "Ce fichier existe déjà. Choisis un nouveau nom pour conserver l'original.":'This file exists. Choose a new name to preserve the original.',
    'Le fichier existant est conservé. Enregistre cette version sous un nouveau nom.':'Existing file preserved. Save this version under a new name.',
    "La disposition n'a pas été enregistrée.":'The layout was not saved.', 'Import refusé : la disposition actuelle est conservée.':'Import rejected: current layout preserved.',
    'Le fichier doit contenir schema, background et widgets.':'The file must contain schema, background and widgets.',
    'Format de disposition non pris en charge.':'Unsupported layout format.',
    'La couleur du fond doit être au format #RRGGBB.':'Background color must use #RRGGBB.',
    'La disposition doit contenir entre une et six jauges.':'The layout must contain one to six gauges.',
    'Une jauge contient des champs manquants ou inconnus.':'A gauge contains missing or unknown fields.',
    'Chaque jauge doit avoir un identifiant unique valide.':'Each gauge needs a valid unique identifier.',
    "Chaque voie CH1 à CH6 ne peut apparaître qu'une fois.":'Each channel CH1 to CH6 can appear only once.',
    'Type de jauge inconnu.':'Unknown gauge type.', 'La jauge dépasse la zone modifiable.':'The gauge is outside the editable panel.',
    'Deux jauges se chevauchent.':'Two gauges overlap.', "La couleur d'une jauge doit être au format #RRGGBB.":'Gauge color must use #RRGGBB.',
    'Fichier incompatible':'Incompatible file', 'Fichier prêt':'File ready', 'Fichier officiel':'Official file',
    'Le fichier officiel 2.0.5 est vérifié et sélectionné. L’installation sur la radio reste séparée.':'Official 2.0.5 file verified and selected. Installation on the radio is a separate action.',
    "Le fichier officiel 2.0.5 est vérifié et sélectionné. L'installation sur la radio reste séparée.":'Official 2.0.5 file verified and selected. Installation on the radio is a separate action.',
    'Firmware officiel 2.0.5 sélectionné · fichier vérifié':'Official 2.0.5 firmware selected · file verified',
    'Firmware officiel 2.0.5':'Official 2.0.5 firmware', 'Firmware DDF':'DDF firmware', 'Tous les fichiers':'All files',
    'Chemin de démarrage trop long pour Windows.':'Startup path is too long for Windows.',
    'Destination de démarrage redirigée : opération refusée.':'Redirected startup destination: operation refused.',
    'Exécutable Windows non reconnu.':'Unrecognized Windows executable.',
    'La copie de démarrage est différente. Aucune inscription Windows effectuée.':'Startup copy differs. No Windows startup entry was written.',
    'Le démarrage automatique nécessite l’exécutable Windows compilé.':'Automatic startup requires the compiled Windows executable.',
    'Option disponible sur Windows uniquement.':'Available on Windows only.',
    'Une entrée de démarrage différente porte déjà ce nom. Elle a été conservée.':'A different startup entry already uses this name. It was preserved.',
    'Taille de mémoire non prise en charge.':'Unsupported memory size.', 'Géométrie du mode maintenance inconnue.':'Unknown maintenance-mode geometry.',
    'Branche une seule DDF-350 en mode mise à jour, puis réessaie.':'Connect one DDF-350 in update mode, then retry.',
    'Accès exclusif refusé. Ferme les fenêtres ouvertes sur la radio, puis réessaie.':'Exclusive access refused. Close windows accessing the radio, then retry.',
    'Firmware installé inconnu. Sauvegarde conservée ; aucun transfert autorisé.':'Unknown installed firmware. Backup preserved; transfer refused.',
    'Firmware installé reconnu : ':'Installed firmware recognized: ', ' blocs à transférer.':' blocks to transfer.',
    'Lecture de la mémoire pour la sauvegarde…':'Reading memory for backup…', 'Sauvegarde enregistrée et vérifiée sur le PC.':'Backup saved and verified on PC.',
    'Processus administrateur démarré. Demande d’accès exclusif…':'Administrator process started. Requesting exclusive access…',
    'Volume USB verrouillé. Contrôle de l’identité du disque…':'USB volume locked. Checking disk identity…',
    'Identité USB confirmée, accès protégé prêt.':'USB identity confirmed; protected access ready.',
    'Relecture finale de toute la mémoire…':'Final readback of all memory…', 'Transfert : ':'Transfer: ', ' blocs vérifiés':' blocks verified',
    'Installation vérifiée. Débranche maintenant le câble USB.':'Installation verified. Disconnect the USB cable now.',
    'Transfert terminé. Rallume la radio avec Power uniquement.':'Transfer complete. Restart the radio using Power only.',
    ' Débranche maintenant l’USB ; garde la radio éteinte.':' Disconnect USB now; keep the radio off.',
    'Demande Windows annulée.':'Windows prompt cancelled.', 'Demande incorrecte.':'Invalid request.',
    'Cible modifiée ou inconnue.':'Modified or unknown target.', 'Cible hors mémoire application.':'Target outside application memory.',
    'Fichier cible non reconnu.':'Unrecognized target file.', 'La radio détectée a changé. Recommence la connexion.':'Detected radio changed. Reconnect it.',
    'Identification USB incohérente.':'Inconsistent USB identity.', 'Identification USB modifiée après verrouillage.':'USB identity changed after locking.',
    'Lecture USB incomplète.':'Incomplete USB read.', 'Transfert USB incomplet. Garde la radio éteinte.':'Incomplete USB transfer. Keep the radio off.',
    'Mémoire modifiée depuis la sauvegarde.':'Memory changed since backup.', 'Sauvegarde locale différente.':'Local backup differs.',
    'Relecture du transfert différente. Arrêt.':'Transfer readback differs. Stopping.', 'Contrôle final de la mémoire différent.':'Final memory verification differs.',
    'Dossier de transfert hors application.':'Transfer folder outside application storage.', 'Dossier de transfert redirigé.':'Redirected transfer folder.',
    'Compte rendu hors application.':'Report outside application storage.', 'Journal hors application.':'Log outside application storage.',
    'Nom de journal incorrect.':'Invalid log name.', 'Numéro de disque incorrect.':'Invalid disk number.', 'Disque USB remplacé.':'USB disk replaced.',
    'Lecture hors profil.':'Read outside supported profile.', 'Écriture hors profil.':'Write outside supported profile.',
    'Installation disponible sur Windows uniquement.':'Installation available on Windows only.', 'Windows requis.':'Windows required.',
    'Lancement administrateur impossible : ':'Unable to launch administrator process: ', 'Initialisation de la demande Windows impossible : ':'Unable to initialize Windows prompt: ',
    'Windows n’a pas renvoyé le processus d’installation.':'Windows did not return the installation process.',
    'Lecture en direct':'Live input', 'En attente de la radio USB':'Waiting for USB radio', 'Aucune donnée reçue':'No data received',
    'CH2 · Gaz / frein':'CH2 · Throttle / brake', 'DDF-350 · CH1 et CH2':'DDF-350 · CH1 and CH2',
    'Valeurs brutes : 0 à 2047  ·  Centre attendu : 1023':'Raw values: 0 to 2047  ·  Expected center: 1023',
    'Dernière donnée : il y a ':'Last data: ', 'Données périmées · aucune nouvelle réception':'Stale data · no new input',
    'Radio connectée · en attente de données':'Radio connected · waiting for data', 'Radio déconnectée':'Radio disconnected',
    'Radio non détectée':'Radio not detected', 'Lecture arrêtée.':'Reading stopped.', 'Lecture DDF-350':'DDF-350 input',
    'Ce lecteur nécessite Windows.':'This reader requires Windows.', 'Rapport rejeté : ':'Report rejected: ',
    'Aperçu schématique':'Schematic preview', 'Chargement…':'Loading…',
}
EN.update({
    'Barres segmentées · vert et cyan':'Segmented bars · lime and cyan',
    'Deux cadrans segmentés · vert et cyan':'Two segmented dials · lime and cyan',
    'Deux aiguilles · violet et vert':'Two needles · purple and lime',
    'CH1 à CH4 : −100 % à +100 %, neutre à 0 %. Les jauges CH3/CH4 sont centrées au neutre. Valeurs d’exemple.':
        'CH1–CH4: −100% to +100%, neutral at 0%. CH3/CH4 gauges are centered at neutral. Example readings.',
})
EN.update({'Personnalise la grille du bas. Le haut reste d’origine.':'Edit the lower grid. The top stays original.',
'Grille B · le haut reste d’origine':'Grid B · original upper dashboard',
'A · HAUT D’ORIGINE':'A · ORIGINAL UPPER AREA','B · GRILLE MODIFIABLE · 6 × 4':'B · EDITABLE GRID · 6 × 4',
'Cette ancienne composition ne contient aucun bloc dans B.':'This older layout has no blocks in B.',
'Partie B importée. Le haut reste d’origine.':'Lower grid imported. The top stays original.'})
EN['Valeurs d’exemple']='Sample values'
EN.update({'Haut : pile seule':'Top: battery only',
           'Haut du dashboard modifié.':'Upper dashboard updated.',
           'Personnalise la grille du bas et le style du haut.':'Customize the lower grid and upper style.',
           'Grille B · jauges du bas':'Grid B · lower gauges'})
_substitutions=re.compile('|'.join(re.escape(key) for key in sorted(EN,key=len,reverse=True)))

def set_language(language):
    global _language
    if language not in LANGUAGES:raise ValueError('Unsupported language')
    _language=language

def language():return _language

def tr(text):
    if not isinstance(text,str) or _language=='fr':return text
    if text in EN:return EN[text]
    # Dynamic statuses contain filenames, channel values or exception text.
    # Translation is applied only at display boundaries; source/model values
    # and worker payloads are never passed through this function.
    return _substitutions.sub(lambda match:EN[match.group()],text)

class StringVar(tk.StringVar):
    """Display status variable. Never use for paths, IDs or model values."""
    def set(self,value):
        self.source_text=value
        super().set(tr(value))
    def __init__(self,*args,**kwargs):
        self.source_text=kwargs.get('value','')
        if 'value' in kwargs:kwargs['value']=tr(self.source_text)
        super().__init__(*args,**kwargs)

def preferences_path():
    return Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'DDF350-USB-Toolkit'/'preferences.json'

def load_language():
    path=preferences_path()
    try:
        if path.is_symlink() or path.stat().st_size>4096:return DEFAULT_LANGUAGE
        data=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data,dict):return DEFAULT_LANGUAGE
        return data['language'] if data.get('schema')==2 and data.get('language') in LANGUAGES else DEFAULT_LANGUAGE
    except (OSError,ValueError,TypeError,KeyError):return DEFAULT_LANGUAGE

def save_language(value):
    if value not in LANGUAGES:raise ValueError('Unsupported language')
    path=preferences_path()
    for ancestor in (path,*path.parents):
        if ancestor.exists() and (ancestor.is_symlink() or getattr(ancestor.lstat(),'st_file_attributes',0)&1024):
            raise OSError('Redirected preferences path')
    path.parent.mkdir(parents=True,exist_ok=True)
    import tempfile
    fd,name=tempfile.mkstemp(prefix='preferences-',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump({'schema':2,'language':value},stream);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        try:Path(name).unlink()
        except FileNotFoundError:pass

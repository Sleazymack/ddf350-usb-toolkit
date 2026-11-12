# DDF-350 USB Toolkit · 0.7.1
[English](README.md)

[Télécharger la version portable Windows 0.7.1](https://github.com/Sleazymack/ddf350-usb-toolkit/releases/download/v0.7.1/DDF350-Portable-Public-v0.7.1.zip) · [Notes de version](https://github.com/Sleazymack/ddf350-usb-toolkit/releases/tag/v0.7.1) · [Avertissement bêta](BETA-WARNING.txt)

Cette application portable pour Windows 64 bits permet de lire la direction (CH1) et les gaz/frein (CH2) par USB-C, de choisir parmi six dashboards ou de créer une composition avec une photo et des jauges.

**Compatibilité : DDF-350 matériel 1.0, logiciel 2.0.5.** Vérifie les deux versions sur la radio. Chaque release GitHub intègre le firmware officiel DumboRC 2.0.5 dans l’EXE. L’assistant vérifie son empreinte SHA-256 et l’utilise automatiquement comme base pour créer ton dashboard. Tu trouveras aussi une copie du fichier d’origine dans le ZIP sous `firmware/DDF-2.0.5.bin`. Pour une radio plus ancienne, suis d’abord la [procédure de mise à jour du fabricant](https://www.dumborc.com/?page_id=930).

1. Extrais le ZIP portable public et lance **DDF350-USB-Toolkit.exe**. Tu peux passer de l’anglais au français en haut à droite.
2. Dans **Composition personnelle → Style**, choisis ta photo et coche **Haut : pile seule**. La partie supérieure affiche la photo avec une petite batterie en haut à gauche. Décoche pour retrouver le haut d’origine tout en gardant ta photo et tes jauges.
3. À l’étape 4, garde le démarrage d’origine, choisis une photo PNG/JPEG/BMP centrée à 80 %, ou importe un GIF personnel de moins de 280 Ko, à 5 images/s et 4 s maximum. Vérifie l’aperçu puis clique sur **Utiliser ce rendu**.
4. Véhicule éteint, suis les étapes de transfert de l’assistant. L’outil vérifie la sauvegarde avant l’écriture et relit le résultat. Une installation reconnue peut être remplacée. Le dashboard « Original » garde la modification USB ; pour rétablir la radio d’usine, réinstalle le firmware officiel. Une version inconnue arrête le transfert. Garde le câble branché jusqu’à la fin de la vérification.
5. Pour jouer sur PC, démarre normalement et ouvre **PC** dans l’application. Le lecteur peut rester dans la zone de notification pour se reconnecter.

La photo utilise l’affichage fixe natif. La lecture GIF reste expérimentale : un blocage a été signalé. Les limites ne garantissent pas la stabilité sur la radio.

[Compilation et tests](CONTRIBUTING.md) · [Médias de démarrage](docs/startup-media.md) · [Licence](LICENSE) · [Crédits](CREDITS.md)

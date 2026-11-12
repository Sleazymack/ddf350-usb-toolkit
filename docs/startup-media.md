# Startup screen · 0.7.1

Original startup is the default. To remove an older installed animation, select **Keep original startup** and transfer the newly prepared dashboard. Legacy outputs are still recognized by exact regeneration.

**Still photo (PNG, JPEG, BMP).** The photo is fitted without cropping or distortion into a centered 192 × 256 box on the 240 × 320 LCD, with black margins. EXIF orientation is respected; transparency is composited over black. A flash-resident RGB565 bitmap is drawn on a child of the normal native welcome page. It follows the stock startup transition; there is no frame player, extra timer or fixed two-second delay for a photo.

**Personal animated GIF (experimental).** Both the original file and the radio asset must be strictly smaller than 280,000 bytes. Every frame must last 200–1,000 ms: no frame can exceed 5 fps, even when the average fps is lower. Use 2–20 frames, at most 4 seconds in total. The wizard rejects out-of-range files instead of silently speeding up, dropping frames or trimming the sequence. Set the speed in your GIF editor before importing. Source loop metadata is ignored: the radio plays the sequence once. Output is 96 × 110, 16 colors. The preview displays the decoded colors and original frame delays. GIF playback has frozen a transmitter; these limits are application limits, not a manufacturer guarantee.

Import a local file at step 4. The preview uses the converted data. Select **Use this preview** to apply it. Nothing is applied just by viewing a file. No GIF preset is included. Normal dashboard functions and Windows synchronization are separate from this choice.

**Français :** garde le démarrage d’origine ou choisis une photo fixe centrée à 80 %. Pour un GIF personnel : moins de 280 Ko (280 000 octets), 5 images/s maximum, entre 200 et 1 000 ms par image, 2 à 20 images, 4 secondes au total, sans boucle. Si la radio se fige, choisis **Garder le démarrage d’origine** et retransfère ton dashboard.

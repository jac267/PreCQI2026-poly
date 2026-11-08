# Opération Déneigement - Kits de départ

Les règles du jeu sont dans le cahier de charges.

Trois kits, au choix : `python/`, `typescript/`, `java/`. Chacun lit l'état du jeu,
appelle votre bot et envoie ses ordres. Le bot fourni déplace chaque déneigeuse au hasard :
toute la stratégie est à écrire.

| Kit | Fichier à modifier | Le reste |
| --- | --- | --- |
| Python | `bot.py` | `models.py` (classes de l'état), `main.py` (boucle réseau) |
| TypeScript | `src/bot.ts` | `src/models.ts` (types), `src/main.ts` (boucle réseau) |
| Java | `src/main/java/bot/Bot.java` | `Models.java` (classes), `Main.java` (boucle réseau) |

## Tester sur votre machine

Il suffit d'avoir Docker. Dans le dossier du kit :

```sh
docker compose up --build
```

Cette commande lance un serveur de jeu local (image Docker fournie par l'organisation) et
votre bot. Options :

```sh
SEED=42 docker compose up --build          # rejouer exactement la même partie
TICK_MS=50 docker compose up --build       # partie accélérée
WAIT_FOR_ALL=1 docker compose up --build   # le tour attend votre bot (pour déboguer)
```

Suivez la partie sur http://localhost:8080

## Remettre votre code

Compressez le dossier du kit en `.zip`, avec le `Dockerfile` à la racine, et remettez-le sur
la plateforme. Vous pouvez ajouter des bibliothèques (`requirements.txt`, `package.json`,
`pom.xml`) : elles sont installées pendant la construction de l'image.

Pendant les parties, votre bot :

- reçoit l'adresse du serveur dans la variable d'environnement `SERVER_URL` ;
- n'a accès à aucun autre réseau (rien à télécharger pendant la partie) ;
- dispose de 1 processeur et de 512 Mo de mémoire ;
- ne peut écrire que dans `/tmp` ;
- tourne avec un utilisateur non privilégié (pas root).

Pendant la construction de l'image, seuls les dépôts de bibliothèques (PyPI, npm, Maven
Central, Debian) sont accessibles.

Ce que votre bot affiche (stdout et stderr) est visible sur la plateforme après chaque partie.

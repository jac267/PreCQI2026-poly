# Opération Déneigement - Kits de départ

Les règles du jeu sont dans le cahier de charges.

Trois kits, au choix : `python/`, `typescript/`, `java/`. Chacun lit l'état du jeu,
appelle votre bot et envoie ses ordres. Les bots TypeScript et Java déplacent chaque
déneigeuse au hasard. La stratégie Python est décrite ci-dessous.

| Kit | Fichier à modifier | Le reste |
| --- | --- | --- |
| Python | `bot.py` | `models.py` (classes de l'état), `main.py` (boucle réseau) |
| TypeScript | `src/bot.ts` | `src/models.ts` (types), `src/main.ts` (boucle réseau) |
| Java | `src/main/java/bot/Bot.java` | `Models.java` (classes), `Main.java` (boucle réseau) |

## Stratégie Python

Le bot Python achète trois déneigeuses normales, en plus de celle reçue au départ,
puis uniquement de grosses déneigeuses. Il achète lorsqu'il a assez d'argent et que
le garage est libre, jusqu'à une flotte de huit déneigeuses (pannes comprises).
Pour la collecte générale, chaque déneigeuse explore un arbre dont chaque niveau
représente un déplacement d'une case et choisit le premier mouvement du préfixe qui maximise :

```text
neige ramassée / (nombre de déplacements + distance au dépôt accessible le plus proche)
```

Tous les préfixes non vides sont évalués, même avant que la charge soit pleine.
La neige ramassée est limitée à la capacité restante, sans compter la charge déjà
à bord. Les visites sont propres à chaque branche : la case de départ compte
comme déjà visitée et tout retour sur une case déjà visitée dans cette branche
est interdit. Une branche pleine n'est plus développée.

La stratégie d'appels 311 de `origin/main` est intégrée aux déneigeuses normales
et grosses. Les appels sont classés par récompense divisée par l'effectif estimé :
la neige sur le chemin appel-dépôt, avec une marge de 20 %, divisée par la capacité
et arrondie vers le haut (au moins une déneigeuse). Les bots sains les plus proches
sont affectés s'ils peuvent arriver avant l'expiration et si au moins 60 % de cet
effectif est disponible. Chaque bot n'est affecté qu'à un appel à la fois.

Les bots affectés rejoignent le corridor dépôt-appel et le suivent vers l'appel.
Les appels passent avant la collecte générale, tout en respectant les mutex et la
capacité restante. Un corridor devenu indisponible peut être contourné si le délai
le permet ; sinon, le bot reprend la recherche en arbre. Les charges pleines sont
rapportées au dépôt accessible le plus proche et les pannes restent prioritaires.

Chaque case franchissable possède un mutex avec l'identifiant de son propriétaire.
Les positions actuelles de nos déneigeuses sont réservées avant la planification.
Les déneigeuses choisissent ensuite leur trajet séquentiellement et verrouillent
toutes ses cases, y compris le retour au dépôt ou le trajet de réparation au garage.
Les cases appartenant à une autre déneigeuse sont retirées de l'arbre et des chemins
de retour. Un verrouillage de trajet est atomique : il réussit pour toutes les cases
ou ne réserve rien. Sans trajet disponible, la déneigeuse attend.

Les mutex sont reconstruits à chaque tour pour permettre à chaque déneigeuse de
replanifier sans laisser de réservations périmées. Après les affectations aux appels,
l'ordre de priorité tourne à chaque tour pour répartir l'accès aux trajets restants.

Les distances et premiers mouvements entre toutes les cases sont précalculés
quand la carte est connue, puis conservés en mémoire entre les tours. Un changement
de carte invalide le cache. Les cases occupées sont évitées, avec recalcul des
retours lorsque ces obstacles temporaires modifient les chemins. Le bot livre
aussi une charge partielle lorsqu'il est adjacent à un dépôt, ou retourne au dépôt
si aucune collecte rentable n'est possible. Une déneigeuse brisée rejoint son garage.

L'exploration construit les branches au fil du parcours pour limiter la mémoire,
sans plafond de profondeur, de temps ou de nombre de noeuds. Elle reste exponentielle :
une carte peu enneigée peut dépasser le délai d'un tour, même si les chemins sont
déjà précalculés. `WAIT_FOR_ALL=1` permet de l'observer en mode debug local.

Tests du planificateur depuis la racine du dépôt :

```sh
python3 -m unittest discover -s python -v
```

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

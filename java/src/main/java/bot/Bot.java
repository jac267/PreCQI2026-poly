package bot;

import java.util.Random;

import bot.Models.GameState;
import bot.Models.Orders;
import bot.Models.Plow;

/**
 * Votre bot. C'est le seul fichier que vous avez besoin de modifier.
 *
 * decide() est appelée à chaque tour avec l'état du jeu et doit retourner vos ordres.
 * Pour l'instant, chaque déneigeuse se déplace au hasard.
 */
public class Bot {
    private static final String[] DIRECTIONS = {"N", "S", "E", "O"};
    private final Random random = new Random();

    public Orders decide(GameState state) {
        Orders orders = new Orders();
        for (Plow plow : state.myPlows()) {
            orders.move(plow, DIRECTIONS[random.nextInt(DIRECTIONS.length)]);
        }
        return orders;
    }
}

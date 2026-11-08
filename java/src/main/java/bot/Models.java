package bot;

import java.util.ArrayList;
import java.util.List;

/** Classes qui représentent l'état du jeu reçu à chaque tour et les ordres à envoyer. */
public final class Models {
    private Models() {}

    public record Position(int x, int y) {}

    /** type : "normal" ou "big". load vaut null pour les déneigeuses des autres équipes. */
    public record Plow(String id, String team, Position position, String type, boolean broken, Integer load) {}

    public record Call(String id, Position position, int reward, int expiresAt) {}

    /** tiles.get(y).charAt(x) : '.' rue, '#' bâtiment, 'D' dépôt, 'G' garage. snow[y][x] : unités de neige. */
    public record GameMap(int width, int height, List<String> tiles, int[][] snow) {
        public char tile(int x, int y) {
            return tiles.get(y).charAt(x);
        }
    }

    public record PlowCost(int normal, int big) {}

    public record Constants(int maxTicks, int tickMs, int plowCapacity, PlowCost plowCost, int maxSnow,
                            int callRewardMin, int callRewardMax, int callDuration, int snowfallPerTick,
                            int stormTicks, int stormMultiplier) {}

    public record OrderError(String plowId, String reason) {}

    public record GameState(int tick, String you, int money, Position garage, List<Plow> plows, GameMap map,
                            List<Call> calls, List<OrderError> errors, Constants constants) {
        public List<Plow> myPlows() {
            return plows.stream().filter(p -> p.team().equals(you)).toList();
        }
    }

    /** Une action : type "move" (avec direction "N", "S", "E" ou "O") ou "unload". */
    public record Action(String plowId, String type, String direction) {}

    public static final class Orders {
        public int tick;
        public final List<Action> actions = new ArrayList<>();
        /** null, "normal" ou "big". */
        public String buy;

        public void move(Plow plow, String direction) {
            actions.add(new Action(plow.id(), "move", direction));
        }

        public void unload(Plow plow) {
            actions.add(new Action(plow.id(), "unload", null));
        }
    }
}

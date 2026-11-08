package bot;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

import com.google.gson.Gson;

import bot.Models.GameState;
import bot.Models.OrderError;
import bot.Models.Orders;

/**
 * Boucle réseau : lit l'état du jeu, appelle Bot.decide(), envoie les ordres.
 * Vous n'avez normalement pas besoin de modifier ce fichier.
 */
public class Main {
    public static void main(String[] args) throws InterruptedException {
        String env = System.getenv("SERVER_URL");
        String serverUrl = (env != null ? env : "http://localhost:8080/teams/red").replaceAll("/$", "");
        HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
        Gson gson = new Gson();
        Bot bot = new Bot();
        System.out.println("connexion à " + serverUrl);

        int tick = -1;
        while (true) {
            HttpResponse<String> response;
            try {
                HttpRequest get = HttpRequest.newBuilder(URI.create(serverUrl + "/state?after=" + tick))
                        .timeout(Duration.ofSeconds(35)).GET().build();
                response = http.send(get, HttpResponse.BodyHandlers.ofString());
            } catch (Exception e) {
                Thread.sleep(500); // serveur pas encore prêt
                continue;
            }
            if (response.statusCode() == 410) {
                System.out.println("partie terminée : " + response.body());
                return;
            }
            if (response.statusCode() == 408) continue; // aucun nouveau tour, on redemande
            if (response.statusCode() != 200) {
                System.out.println("erreur du serveur : " + response.statusCode());
                Thread.sleep(500);
                continue;
            }

            GameState state = gson.fromJson(response.body(), GameState.class);
            tick = state.tick();
            for (OrderError error : state.errors()) {
                System.out.println("tour " + tick + " : ordre refusé " + error);
            }

            Orders orders;
            try {
                orders = bot.decide(state);
            } catch (Exception e) {
                e.printStackTrace();
                orders = new Orders();
            }
            orders.tick = tick;

            try {
                HttpRequest post = HttpRequest.newBuilder(URI.create(serverUrl + "/orders"))
                        .header("Content-Type", "application/json")
                        .POST(HttpRequest.BodyPublishers.ofString(gson.toJson(orders))).build();
                HttpResponse<String> sent = http.send(post, HttpResponse.BodyHandlers.ofString());
                if (sent.statusCode() == 409) {
                    System.out.println("tour " + tick + " : ordres arrivés trop tard");
                } else if (sent.statusCode() != 200) {
                    System.out.println("ordres refusés : " + sent.statusCode() + " " + sent.body());
                }
            } catch (Exception e) {
                e.printStackTrace();
            }
        }
    }
}

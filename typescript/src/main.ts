// Boucle réseau : lit l'état du jeu, appelle decide(), envoie les ordres.
// Vous n'avez normalement pas besoin de modifier ce fichier.

import { decide } from "./bot";
import { GameState, Orders } from "./models";

const SERVER_URL = (process.env.SERVER_URL ?? "http://localhost:8080/teams/red").replace(/\/$/, "");

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function main(): Promise<void> {
  console.log(`connexion à ${SERVER_URL}`);
  let tick = -1;
  while (true) {
    let response: Response;
    try {
      response = await fetch(`${SERVER_URL}/state?after=${tick}`, { signal: AbortSignal.timeout(35_000) });
    } catch {
      await sleep(500); // serveur pas encore prêt
      continue;
    }
    if (response.status === 410) {
      console.log("partie terminée :", await response.text());
      return;
    }
    if (response.status === 408) continue; // aucun nouveau tour, on redemande
    if (!response.ok) {
      console.log("erreur du serveur :", response.status);
      await sleep(500);
      continue;
    }

    const state = (await response.json()) as GameState;
    tick = state.tick;
    for (const error of state.errors) {
      console.log(`tour ${tick} : ordre refusé`, error);
    }

    let orders: Orders;
    try {
      orders = decide(state);
    } catch (e) {
      console.error(e);
      orders = { actions: [] };
    }

    try {
      const sent = await fetch(`${SERVER_URL}/orders`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tick, ...orders }),
      });
      if (sent.status === 409) console.log(`tour ${tick} : ordres arrivés trop tard`);
      else if (!sent.ok) console.log("ordres refusés :", sent.status, await sent.text());
    } catch (e) {
      console.error(e);
    }
  }
}

main();

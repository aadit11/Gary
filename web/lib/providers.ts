// App connectors shown in onboarding and on the landing page. Storage keys map to CareProfile.connectors.

export type Key = "doordash" | "uber" | "groceries";

export const PROVIDERS: {
  key: Key;
  name: string;
  logo: string;
  color: string;
  does: string;
  bullets: string[];
}[] = [
  {
    key: "groceries",
    name: "Instacart",
    logo: "https://cdn.simpleicons.org/instacart/43B02A",
    color: "#43B02A",
    does: "get groceries",
    bullets: ["Restock essentials from the usual store", "Reads every item and the total back first", "Large or new orders wait for your okay"],
  },
  {
    key: "uber",
    name: "Uber",
    logo: "https://cdn.simpleicons.org/uber/000000",
    color: "#000000",
    does: "book rides",
    bullets: ["Book a ride to the doctor or the pharmacy", "Says the car and driver out loud when it's on the way", "You get a message with every trip"],
  },
  {
    key: "doordash",
    name: "DoorDash",
    logo: "https://cdn.simpleicons.org/doordash/FF3008",
    color: "#FF3008",
    does: "order food",
    bullets: ["Order dinner, or \"the usual\", by phone", "Reads the order and total back before placing it", "Anything unusual waits for your okay"],
  },
];

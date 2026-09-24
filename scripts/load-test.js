import http from "k6/http";
import { sleep } from "k6";

export const options = {
  vus: 5,
  duration: "2m",
};

const BASE = __ENV.CHECKOUT_URL || "http://localhost:8000";

export default function () {
  http.get(`${BASE}/checkout`);
  sleep(0.2);
}

from machine import ADC, Pin, Timer
import time, sys, uselect

# -------------------------------
# Configuración
# -------------------------------
FS = 250                     # Frecuencia de muestreo
DT_MS = int(1000 / FS)       # Periodo en ms
N = 5                        # Ventana de promedio/mediana
ALPHA = 0.15                # Constante filtro exponencial
SKIP = 10                    # Cada cuántas muestras se imprime

adc = ADC(Pin(34))           # Entrada en GPIO34
adc.atten(ADC.ATTN_11DB)     # Rango hasta 3.3V
adc.width(ADC.WIDTH_12BIT)   # Resolución 12 bits (0-4095)

led = Pin(2, Pin.OUT)        # LED indicador
led.on()

# -------------------------------
# Variables
# -------------------------------
ring = [0]*N
idx = 0
llen = 0
ema = None
new = False
valor = 0
count = 0

# Estados de visualización (ON/OFF)
show_raw = False
show_avg = False
show_med = False
show_exp = False

# -------------------------------
# Timer ISR
# -------------------------------
def handler(t):
    global valor, new
    valor = adc.read()
    new = True

timer = Timer(0)
timer.init(period=DT_MS, mode=Timer.PERIODIC, callback=handler)

# -------------------------------
# Polling teclado
# -------------------------------
poll = uselect.poll()
poll.register(sys.stdin, uselect.POLLIN)

print("\n--- Selección de señales ---")
print("1 → Alternar RAW (señal cruda)")
print("2 → Alternar Promedio móvil")
print("3 → Alternar Mediana")
print("4 → Alternar Exponencial")
print("-----------------------------")

try:
    while True:
        # --- Control desde teclado ---
        if poll.poll(0):
            cmd = sys.stdin.readline().strip()
            if cmd == "1": show_raw = not show_raw
            elif cmd == "2": show_avg = not show_avg
            elif cmd == "3": show_med = not show_med
            elif cmd == "4": show_exp = not show_exp
            print(f"RAW:{show_raw}, AVG:{show_avg}, MED:{show_med}, EXP:{show_exp}")

        # --- Nueva muestra ---
        if new:
            new = False
            v = valor
            ring[idx] = v
            idx = (idx + 1) % N
            llen = min(llen + 1, N)
            window = ring[:llen]

            avg = sum(window) // llen
            med = sorted(window)[llen // 2]
            ema = v if ema is None else int(ALPHA*v + (1-ALPHA)*ema)

            # --- Construcción de salida con nombres ---
            datos = []
            if show_raw: datos.append(f"RAW:{v}")      
            if show_avg: datos.append(f"AVG:{avg}")    
            if show_med: datos.append(f"MED:{med}")    
            if show_exp: datos.append(f"EXP:{ema}")    

            # --- Mostrar cada SKIP muestras ---
            count += 1
            if count >= SKIP and datos:
                count = 0
                print(" | ".join(datos))

            time.sleep_ms(1)

except KeyboardInterrupt:
    pass
finally:
    timer.deinit()
    led.off()
    print("Programa detenido")

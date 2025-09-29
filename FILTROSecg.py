from machine import ADC, Pin, Timer            # Importa periféricos de ESP32: ADC (analógico), Pin (GPIO), Timer (interrupciones periódicas)
import time, sys, uselect                      # time (pausas), sys (E/S estándar), uselect (lectura no bloqueante de teclado)

# -------------------------------
# Configuración
# -------------------------------
FS = 250                                       # Frecuencia de muestreo en Hz (250 muestras por segundo)
DT_MS = int(1000 / FS)                         # Periodo del muestreo en milisegundos (1000/FS → ~4 ms)
N = 5                                          # Tamaño de ventana para filtros por ventana (promedio/mediana)
ALPHA = 0.15                                   # Constante del filtro exponencial (0..1) → suavizado EMA
SKIP = 10                                      # Imprime/guarda 1 de cada 10 muestras para no saturar la consola
FILE_NAME = "ecg_data.txt"                     # Nombre del archivo de salida (texto) para registro de datos

adc = ADC(Pin(34))                             # Configura el ADC leyendo por el pin GPIO34 (entrada analógica)
adc.atten(ADC.ATTN_11DB)                       # Atenuación 11 dB → rango aprox. 0–3.3V
adc.width(ADC.WIDTH_12BIT)                     # Resolución del ADC: 12 bits (0–4095)

led = Pin(2, Pin.OUT)                          # LED en GPIO2 como indicador de ejecución
led.on()                                       # Enciende LED para indicar que el sistema está activo

# -------------------------------
# Variables
# -------------------------------
ring = [0]*N                                   # Buffer circular de N muestras (para promedio/mediana)
idx = 0                                        # Índice actual de escritura en el buffer circular
llen = 0                                       # Cantidad efectiva de datos cargados en el buffer (crece hasta N)
ema = None                                     # Memoria del filtro exponencial; None indica que aún no se inicializa
new = False                                    # Bandera: indica que llegó nueva muestra desde la ISR
valor = 0                                      # Último valor crudo (RAW) leído del ADC
count = 0                                      # Contador para controlar el SKIP de impresión/guardado

# Estado de visualización
modo = 1                                       # Modo activo:
                                               # 1=solo RAW, 2=RAW+PROM, 3=RAW+MED, 4=RAW+EXP, 5=solo FILTRADA

# Buffer para almacenamiento en archivo
buffer_lines = []                              # Acumulador de líneas de texto para escribir por lotes (mejora rendimiento/flash)
FLUSH_EVERY = 50                                # Cada cuántas líneas se vuelca el buffer al archivo

# -------------------------------
# Timer ISR
# -------------------------------
def handler(t):                                 # Rutina de interrupción llamada por el Timer cada DT_MS
    global valor, new
    valor = adc.read()                          # Lee una muestra cruda del ADC (0..4095) de forma muy rápida
    new = True                                  # Marca que hay dato nuevo para que el bucle principal lo procese

timer = Timer(0)                                # Instancia el Timer hardware 0
timer.init(period=DT_MS, mode=Timer.PERIODIC,   # Configura timer periódico con periodo DT_MS (≈4 ms a 250 Hz)
           callback=handler)                    # Cada vez que vence el periodo, ejecuta handler()

# -------------------------------
# Polling teclado
# -------------------------------
poll = uselect.poll()                           # Crea objeto de sondeo para E/S no bloqueante
poll.register(sys.stdin, uselect.POLLIN)        # Registra la entrada estándar (teclado) para poder leer sin bloquear

print("\n--- Selección de visualización ---")   # Instrucciones de los modos disponibles
print("1 → Solo RAW")
print("2 → RAW + PROM")
print("3 → RAW + MED")
print("4 → RAW + EXP")
print("5 → Solo FILTRADA (según nivel máximo)")
print("----------------------------------")

try:
    while True:                                 # Bucle principal del programa (corre hasta Ctrl+C)
        # --- Control desde teclado ---
        if poll.poll(0):                        # Revisa si hay tecla disponible (0 ms: no se bloquea)
            cmd = sys.stdin.readline().strip()  # Lee la línea tecleada y quita saltos/espacios
            if cmd in ["1", "2", "3", "4", "5"]:# Si es un modo válido, actualiza el modo activo
                modo = int(cmd)
                print(f"Modo activo: {modo}")   # Feedback al usuario del modo seleccionado

        # --- Nueva muestra ---
        if new:                                 # Solo procesa cuando la ISR dejó una muestra disponible
            new = False                         # Consume la bandera para evitar reprocesar
            v = valor                           # 'v' es la señal cruda (RAW) recién leída
            salida = v                          # 'salida' inicia como RAW (antes de filtros)
            etiqueta = "RAW"                    # Texto para indicar qué filtro produjo 'salida'

            # Buffer para filtros
            ring[idx] = salida                  # Inserta la muestra en el buffer circular
            idx = (idx + 1) % N                 # Avanza el índice circularmente
            llen = min(llen + 1, N)             # Incrementa llenado efectivo hasta N
            window = ring[:llen]                # Ventana actual de muestras válidas para filtrar

            # Filtros en cascada
            if modo >= 2 or modo == 5:          # Si el modo requiere PROM o solo filtrada
                salida = sum(window) // llen    # Promedio (entero) de la ventana
                etiqueta = "PROM"               # Actualiza etiqueta del filtro aplicado

            if modo >= 3 or modo == 5:          # Si el modo requiere MED o solo filtrada
                salida = sorted(window)[llen // 2] # Mediana: ordena y toma el valor central
                etiqueta = "MED"

            if modo >= 4 or modo == 5:          # Si el modo requiere EXP o solo filtrada
                ema = salida if ema is None else int(ALPHA*salida + (1-ALPHA)*ema)
                                                # Filtro exponencial (EMA): inicializa con primera muestra;
                                                # luego mezcla salida actual con histórico según ALPHA
                salida = ema
                etiqueta = "EXP"

            # --- Construcción de salida ---
            count += 1                          # Incrementa contador para SKIP
            if count >= SKIP:                   # Solo imprime/guarda 1 de cada SKIP muestras
                count = 0                       # Reinicia el contador
                if modo == 1:                   # Modo 1: solo cruda
                    linea = f"RAW:{v}\n"
                elif modo in [2, 3, 4]:         # Modo 2-4: cruda + filtrada del nivel alcanzado
                    linea = f"RAW:{v} | {etiqueta}:{salida}\n"
                elif modo == 5:                 # Modo 5: solo la filtrada final
                    linea = f"{etiqueta}:{salida}\n"

                print(linea.strip())            # Muestra la línea en consola (para plotter de Thonny también)
                buffer_lines.append(linea)      # Acumula la línea para escritura por lotes

                # Guardar cada cierto número de líneas
                if len(buffer_lines) >= FLUSH_EVERY:  # Si hay suficientes líneas acumuladas...
                    with open(FILE_NAME, "a") as f:   # Abre archivo en modo anexar
                        f.write(''.join(buffer_lines))# Escribe el bloque de líneas juntas (eficiente)
                    buffer_lines.clear()              # Limpia el buffer en RAM

            time.sleep_ms(1)                   # Pausa muy corta: cede CPU y evita bucle ocupado

except KeyboardInterrupt:                      # Permite salir con Ctrl+C sin error de traza
    pass
finally:
    # Guardar lo pendiente
    if buffer_lines:                           # Si quedaron líneas sin volcar, las escribe ahora
        with open(FILE_NAME, "a") as f:
            f.write(''.join(buffer_lines))
        buffer_lines.clear()

    timer.deinit()                             # Detiene el timer para no seguir generando interrupciones
    led.off()                                  # Apaga el LED (sistema detenido)
    print("Programa detenido. Datos guardados en", FILE_NAME)  # Mensaje final de confirmación


# Импорты и настройки
from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import pandas as pd
import os
import tempfile
import sys
sys.path.append('/opt/airflow/scripts')
from transform_script import transfrom  # Импорт функции transform

# Пути к файлам
BASE_DIR = "/opt/airflow/data"
PROFIT_TABLE_PATH = os.path.join(BASE_DIR, 'profit_table.csv')
FLAGS_ACTIVITY_PATH = os.path.join(BASE_DIR, 'flags_activity.csv')

# Основные аргументы для DAG
default_args = {
    'owner': 'Prokhorova Ekaterina',        # Владелец DAG
    'depends_on_past': False,               # Не зависеть от выполнения предыдущих запусков
    'email_on_failure': False,              # Не отправлять уведомления по электронной почте при ошибках
    'email_on_retry': False,                # Не отправлять уведомления при повторных попытках
    'retries': 1,                           # Количество повторных попыток в случае ошибки
    'retry_delay': timedelta(minutes=5),    # Задержка между повторными попытками
}

# Определение DAG
dag = DAG(
    'etl_kate',  # Имя DAG
    default_args=default_args,
    description='ETL DAG для расчета активности клиентов по продуктам.',
    schedule_interval='0 0 5 * *',  # Запуск 5-го числа каждого месяца
    start_date=datetime(2024, 11, 1), # Дата начала выполнения DAG
    catchup=False, # Не выполнять пропущенные запуски при старте
)

# ЗАДАЧА 1: Извлечение данных
def extract(**context):
    """Извлечение данных из файла profit_table.csv."""
    if not os.path.exists(PROFIT_TABLE_PATH):    # Проверка существования файла
        raise FileNotFoundError(f"Файл {PROFIT_TABLE_PATH} не найден")

    # Копируем данные во временный файл
    with tempfile.NamedTemporaryFile(suffix='.csv', delete=False) as tmp_file:
        profit_table = pd.read_csv(PROFIT_TABLE_PATH)
        profit_table.to_csv(tmp_file.name, index=False) # Сохранение данных во временный файл
        file_path = tmp_file.name

    # Передаём путь к временным данным в XCom
    context['task_instance'].xcom_push(key="profit_data_path", value=file_path)
    print(f"Данные сохранены во временный файл: {file_path}")

# ЗАДАЧА 2: Трансформация данных
def transform(**context):
    """Функция преобразования данных"""
    # Получаем путь к файлу из XCom
    file_path = context['task_instance'].xcom_pull(task_ids='extract_data', key='profit_data_path')
    if not file_path:
        raise ValueError("Путь к файлу отсутствует. Проверьте выполнение задачи 'extract_data'.")

    print(f"Получен путь к исходным данным: {file_path}")

    # Читаем данные
    profit_data = pd.read_csv(file_path)

    # Преобразование данных
    date = context['ds']  # Дата выполнения DAG, используем макрос `ds` из Airflow
    transformed_data = transfrom(profit_data, date)

    # Сохраняем преобразованные данные во временный файл
    with tempfile.NamedTemporaryFile(suffix='.csv', delete=False) as tmp_file:
        transformed_data.to_csv(tmp_file.name, index=False)
        transformed_data_path = tmp_file.name
    print(f"Преобразованные данные сохранены: {transformed_data_path}")

    # Передаём путь к преобразованным данным в XCom
    context['task_instance'].xcom_push(key="transformed_data_path", value=transformed_data_path)

    # Удаляем временный файл с исходными данными после обработки
    if os.path.exists(file_path):
        os.remove(file_path) 
        print(f"Удалён временный файл: {file_path}")

# ЗАДАЧА 3: Загрузка данных
def load(**context):
    """Загрузка данных в файл flags_activity.csv."""
    # Получаем путь к преобразованным данным из XCom
    transformed_data_path = context['task_instance'].xcom_pull(task_ids='transform_data', key='transformed_data_path')
    if not transformed_data_path:
        raise ValueError("Путь к преобразованным данным отсутствует. Проверьте выполнение задачи 'transform_data'.")

    print(f"Получен путь к преобразованным данным: {transformed_data_path}")

    # Читаем преобразованные данные
    transformed_data = pd.read_csv(transformed_data_path)

    # Добавляем данные в файл flags_activity.csv, объединяя с существующими данными (если они есть)
    if os.path.exists(FLAGS_ACTIVITY_PATH):
        existing_data = pd.read_csv(FLAGS_ACTIVITY_PATH)
        combined_data = pd.concat([existing_data, transformed_data]).drop_duplicates()
    else:
        combined_data = transformed_data
    combined_data.to_csv(FLAGS_ACTIVITY_PATH, index=False) # Сохраняем объединенные данные в CSV файл
    print(f"Данные успешно сохранены в {FLAGS_ACTIVITY_PATH}")

    # Удаляем временный файл
    if os.path.exists(transformed_data_path):
        os.remove(transformed_data_path)
        print(f"Удалён временный файл: {transformed_data_path}")

# Определение задач
task_extract = PythonOperator(
    task_id='extract_data',
    python_callable=extract,
    provide_context=True,
    dag=dag,
)

task_transform = PythonOperator(
    task_id='transform_data',
    python_callable=transform,
    provide_context=True,
    dag=dag,
)

task_load = PythonOperator(
    task_id='load_data',
    python_callable=load,
    provide_context=True,
    dag=dag,
)

# Установка зависимостей
task_extract >> task_transform >> task_load

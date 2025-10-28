# alx_travel_app_0x00
The ALX Travel Application | ALX ProDev Backend

## Running Celery with RabbitMQ (development)

1. Run RabbitMQ:
   docker run -d --name rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:3-management

2. Start Django:
   python manage.py runserver

3. Start Celery worker:
   celery -A alx_travel_app worker -l info

4. Create a booking (via API or admin). The booking creates a background task to send a confirmation email.

5. The email is printed to the console (development EMAIL_BACKEND = console).


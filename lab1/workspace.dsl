workspace {
    name "Services provision Platform"
    !identifiers hierarchical

    model {
        client = person "Клиент" "Пользователь, который ищет и заказывает услуги"
        specialist = person "Специалист" "Пользователь, который предоставляет и исполняет услуги"
        admin = person "Администратор" "Сотрудник платформы с расширенными правами доступа"

        paymentSystem = softwareSystem "Платежная система" "Система, которая интегрируется с платформой для обработки оплаты услуг"
        notificationSystem = softwareSystem "Система уведомлений" "Отправляет уведомления пользователям через различные каналы связи"

        serviceProvisionSystem = softwareSystem "Система предоставления услуг" "Платформа, объединяющая клиентов с исполнителями услуг" {
            -> paymentSystem "Обработка платежей"
            -> notificationSystem "Отправка уведомлений"

            apiGateway = container "API Gateway" {
                description "Обрабатывает входящие HTTP-запросы и маршрутизирует их к соответствующим сервисам"
                technology "Python, FastAPI"
                tags "entry-point"
            }

            userService = container "Сервис пользователей" {
                description "Управляет данными пользователей"
                technology "Python, FastAPI"
                tags "user-management"
            }

            serviceService = container "Сервис услуг" {
                description "Управляет каталогом услуг и их параметрами"
                technology "Python, FastAPI"
                tags "service-management"
            }

            orderService = container "Сервис заказов" {
                description "Управляет процессом создания и обработки заказов"
                technology "Python, FastAPI"
                tags "order-management"
            }

            notificationService = container "Сервис уведомлений" {
                description "Отправляет уведомления пользователям"
                technology "Python, FastAPI"
                tags "notification-management"
            }

            paymentService = container "Платежный сервис" {
                description "Интегрируется с внешней платежной системой"
                technology "Python, FastAPI"
                tags "payment-management"
            }

            userDatabase = container "БД пользователей" {
                description "Хранит данные пользователей"
                technology "PostgreSQL"
                tags "storage"
            }

            serviceDatabase = container "БД услуг" {
                description "Хранит данные о предоставляемых услугах"
                technology "PostgreSQL"
                tags "storage"
            }

            orderDatabase = container "БД заказов" {
                description "Хранит данные об оформленных заказах"
                technology "PostgreSQL"
                tags "storage"
            }
        }

        client -> serviceProvisionSystem "Ищет и заказывает услуги" "HTTP/HTTPS"
        specialist -> serviceProvisionSystem "Предоставляет услуги" "HTTP/HTTPS"
        admin -> serviceProvisionSystem "Управляет системой" "HTTP/HTTPS"

        serviceProvisionSystem.apiGateway -> serviceProvisionSystem.userService "HTTP/JSON"
        serviceProvisionSystem.apiGateway -> serviceProvisionSystem.serviceService "HTTP/JSON"
        serviceProvisionSystem.apiGateway -> serviceProvisionSystem.orderService "HTTP/JSON"
        serviceProvisionSystem.apiGateway -> serviceProvisionSystem.paymentService "HTTP/JSON"

        serviceProvisionSystem.userService -> serviceProvisionSystem.userDatabase "CRUD операции" "SQL"
        serviceProvisionSystem.serviceService -> serviceProvisionSystem.serviceDatabase "CRUD операции" "SQL"
        serviceProvisionSystem.orderService -> serviceProvisionSystem.orderDatabase "CRUD операции" "SQL"

        serviceProvisionSystem.userService -> serviceProvisionSystem.notificationService "Запрос на отправку уведомлений" "HTTP/JSON"
        serviceProvisionSystem.orderService -> serviceProvisionSystem.notificationService "Запрос на отправку уведомлений" "HTTP/JSON"
        serviceProvisionSystem.orderService -> serviceProvisionSystem.paymentService "Обработка платежей" "HTTP/JSON"

        serviceProvisionSystem.notificationService -> notificationSystem "Отправка уведомлений" "API"
        serviceProvisionSystem.paymentService -> paymentSystem "Обработка платежей" "API"
    }

    views {
        themes default

        systemContext serviceProvisionSystem "SystemContext" {
            include *
            autoLayout lr
            description "Контекстная диаграмма системы предоставления услуг"
        }

        container serviceProvisionSystem "Containers" {
            include *
            autoLayout
            description "Контейнерная диаграмма системы предоставления услуг"
        }

        dynamic serviceProvisionSystem "CreateUser" "Создание нового пользователя" {
            autoLayout lr
            client -> serviceProvisionSystem.apiGateway "POST /api/users"
            serviceProvisionSystem.apiGateway -> serviceProvisionSystem.userService "POST /users"
            serviceProvisionSystem.userService -> serviceProvisionSystem.userDatabase "INSERT INTO users"
            serviceProvisionSystem.userService -> serviceProvisionSystem.notificationService "Запрос на отправку уведомления о регистрации"
            serviceProvisionSystem.notificationService -> notificationSystem "Отправка уведомления"
        }

        dynamic serviceProvisionSystem "FindUserByLogin" "Поиск пользователя по логину" {
            autoLayout lr
            admin -> serviceProvisionSystem.apiGateway "GET /api/users?login={login}"
            serviceProvisionSystem.apiGateway -> serviceProvisionSystem.userService "GET /users/login/{login}"
            serviceProvisionSystem.userService -> serviceProvisionSystem.userDatabase "SELECT FROM users WHERE login = ?"
        }


        dynamic serviceProvisionSystem "FindSpecialistByNameMask" "Поиск пользователя по маске имени и фамилии" {
            autoLayout lr
            client -> serviceProvisionSystem.apiGateway "GET /api/users?nameMask={mask}"
            serviceProvisionSystem.apiGateway -> serviceProvisionSystem.userService "GET /users/name-mask/{mask}"
            serviceProvisionSystem.userService -> serviceProvisionSystem.userDatabase "SELECT FROM users WHERE name LIKE ? OR surname LIKE ?"
        }

        dynamic serviceProvisionSystem "GetServicesList" "Получение списка услуг" {
            autoLayout lr
            client -> serviceProvisionSystem.apiGateway "GET /api/services"
            serviceProvisionSystem.apiGateway -> serviceProvisionSystem.serviceService "GET /services"
            serviceProvisionSystem.serviceService -> serviceProvisionSystem.serviceDatabase "SELECT FROM services"
        }

        dynamic serviceProvisionSystem "CreateOrder" "Добавление услуг в заказ" {
            autoLayout lr
            client -> serviceProvisionSystem.apiGateway "POST /api/orders"
            serviceProvisionSystem.apiGateway -> serviceProvisionSystem.orderService "POST /orders"
            serviceProvisionSystem.orderService -> serviceProvisionSystem.userService "GET /users/{id}"
            serviceProvisionSystem.userService -> serviceProvisionSystem.userDatabase "SELECT FROM users WHERE id = ?"
            serviceProvisionSystem.orderService -> serviceProvisionSystem.serviceService "GET /services/{id}"
            serviceProvisionSystem.serviceService -> serviceProvisionSystem.serviceDatabase "SELECT FROM services WHERE id = ?"
            serviceProvisionSystem.orderService -> serviceProvisionSystem.orderDatabase "INSERT INTO orders"
        }

        dynamic serviceProvisionSystem "GetUserOrders" "Получение заказов пользователя" {
            autoLayout lr
            client -> serviceProvisionSystem.apiGateway "GET /api/orders/user/{id}"
            serviceProvisionSystem.apiGateway -> serviceProvisionSystem.orderService "GET /orders/user/{id}"
            serviceProvisionSystem.orderService -> serviceProvisionSystem.orderDatabase "SELECT FROM orders WHERE user_id = ?"
        }
    }
}
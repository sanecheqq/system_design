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
                description "Управляет данными пользователей, аутентификацией и авторизацией"
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
        
        serviceProvisionSystem.orderService -> serviceProvisionSystem.serviceService "Получение информации об услугах" "HTTP/JSON"
        serviceProvisionSystem.orderService -> serviceProvisionSystem.userService "Проверка JWT-токена и получение данных пользователя" "HTTP/JSON"
        serviceProvisionSystem.serviceService -> serviceProvisionSystem.userService "Проверка JWT-токена" "HTTP/JSON"

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

        dynamic serviceProvisionSystem "Authentication" "Процесс аутентификации и получения токена" {
            autoLayout lr
            client -> serviceProvisionSystem.apiGateway "POST /api/token с логином и паролем"
            serviceProvisionSystem.apiGateway -> serviceProvisionSystem.userService "POST /token"
            serviceProvisionSystem.userService.authController -> serviceProvisionSystem.userService.userRepository "Проверка учетных данных"
            serviceProvisionSystem.userService -> serviceProvisionSystem.apiGateway "Возврат JWT-токена"
            serviceProvisionSystem.apiGateway -> client "Передача JWT-токена"
        }

        dynamic serviceProvisionSystem "CreateUser" "Создание нового пользователя" {
            autoLayout lr
            client -> serviceProvisionSystem.apiGateway "POST /api/users"
            serviceProvisionSystem.apiGateway -> serviceProvisionSystem.userService "POST /users"
            serviceProvisionSystem.userService.userController -> serviceProvisionSystem.userService.userRepository "Сохранение данных пользователя"
            serviceProvisionSystem.userService -> serviceProvisionSystem.notificationService "Запрос на отправку уведомления о регистрации"
            serviceProvisionSystem.notificationService -> notificationSystem "Отправка уведомления"
            serviceProvisionSystem.userService -> serviceProvisionSystem.apiGateway "Возврат данных созданного пользователя"
            serviceProvisionSystem.apiGateway -> client "Передача результата"
        }

        dynamic serviceProvisionSystem "FindUserByLogin" "Поиск пользователя по логину" {
            autoLayout lr
            admin -> serviceProvisionSystem.apiGateway "GET /api/users?login={login}"
            serviceProvisionSystem.apiGateway -> serviceProvisionSystem.userService "GET /users/login/{login}"
            serviceProvisionSystem.userService.userController -> serviceProvisionSystem.userService.userRepository "Поиск пользователя"
            serviceProvisionSystem.userService -> serviceProvisionSystem.apiGateway "Возврат найденного пользователя"
            serviceProvisionSystem.apiGateway -> admin "Передача результата"
        }

        dynamic serviceProvisionSystem "FindSpecialistByNameMask" "Поиск пользователя по маске имени и фамилии" {
            autoLayout lr
            client -> serviceProvisionSystem.apiGateway "GET /api/users?nameMask={mask}"
            serviceProvisionSystem.apiGateway -> serviceProvisionSystem.userService "GET /users/name-mask/{mask}"
            serviceProvisionSystem.userService.userController -> serviceProvisionSystem.userService.userRepository "Поиск пользователей по маске"
            serviceProvisionSystem.userService -> serviceProvisionSystem.apiGateway "Возврат списка найденных пользователей"
            serviceProvisionSystem.apiGateway -> client "Передача результата"
        }

        dynamic serviceProvisionSystem "CreateService" "Создание новой услуги" {
            autoLayout lr
            specialist -> serviceProvisionSystem.apiGateway "POST /api/services с JWT-токеном"
            serviceProvisionSystem.apiGateway -> serviceProvisionSystem.serviceService "POST /services"
            serviceProvisionSystem.serviceService -> serviceProvisionSystem.userService "Проверка JWT-токена"
            serviceProvisionSystem.serviceService.serviceController -> serviceProvisionSystem.serviceService.serviceRepository "Сохранение данных услуги"
            serviceProvisionSystem.serviceService -> serviceProvisionSystem.apiGateway "Возврат данных созданной услуги"
            serviceProvisionSystem.apiGateway -> specialist "Передача результата"
        }

        dynamic serviceProvisionSystem "GetServicesList" "Получение списка услуг" {
            autoLayout lr
            client -> serviceProvisionSystem.apiGateway "GET /api/services"
            serviceProvisionSystem.apiGateway -> serviceProvisionSystem.serviceService "GET /services"
            serviceProvisionSystem.serviceService.serviceController -> serviceProvisionSystem.serviceService.serviceRepository "Получение списка услуг"
            serviceProvisionSystem.serviceService -> serviceProvisionSystem.apiGateway "Возврат списка услуг"
            serviceProvisionSystem.apiGateway -> client "Передача результата"
        }

        dynamic serviceProvisionSystem "CreateOrder" "Добавление услуг в заказ" {
            autoLayout lr
            client -> serviceProvisionSystem.apiGateway "POST /api/orders с JWT-токеном"
            serviceProvisionSystem.apiGateway -> serviceProvisionSystem.orderService "POST /orders"
            serviceProvisionSystem.orderService -> serviceProvisionSystem.userService "Проверка JWT-токена"
            serviceProvisionSystem.orderService -> serviceProvisionSystem.serviceService "GET /services/{id}"
            serviceProvisionSystem.serviceService.serviceController -> serviceProvisionSystem.serviceService.serviceRepository "Получение данных услуги"
            serviceProvisionSystem.serviceService -> serviceProvisionSystem.orderService "Возврат данных услуги"
            serviceProvisionSystem.orderService.orderController -> serviceProvisionSystem.orderService.orderRepository "Сохранение данных заказа"
            serviceProvisionSystem.orderService -> serviceProvisionSystem.apiGateway "Возврат данных созданного заказа"
            serviceProvisionSystem.apiGateway -> client "Передача результата"
        }

        dynamic serviceProvisionSystem "GetUserOrders" "Получение заказов пользователя" {
            autoLayout lr
            client -> serviceProvisionSystem.apiGateway "GET /api/orders/user/{id} с JWT-токеном"
            serviceProvisionSystem.apiGateway -> serviceProvisionSystem.orderService "GET /orders/user/{id}"
            serviceProvisionSystem.orderService -> serviceProvisionSystem.userService "Проверка JWT-токена"
            serviceProvisionSystem.orderService.orderController -> serviceProvisionSystem.orderService.orderRepository "Получение заказов пользователя"
            serviceProvisionSystem.orderService -> serviceProvisionSystem.apiGateway "Возврат списка заказов"
            serviceProvisionSystem.apiGateway -> client "Передача результата"
        }
    }
}
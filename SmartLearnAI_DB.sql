desc users;

select * from users;
ALTER TABLE users CHANGE password_hash password VARCHAR(255);